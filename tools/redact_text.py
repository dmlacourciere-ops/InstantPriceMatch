# tools/redact_text.py  (stronger patterns)
# Usage:
#   python tools\redact_text.py --in "Master Chat 2025-08-13.txt" --out "Master Chat 2025-08-13.SAFE.txt" --log "Master Chat 2025-08-13.REDACTION_LOG.v2.json"

import argparse, json, os, re, regex, hashlib

def sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()[:8]

# --- Secret patterns ---
# Broadened to catch sk-proj-..., sk-..., etc.
OPENAI_SK = regex.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")

PATTERNS = [
    ("OPENAI_KEY",            OPENAI_SK),
    ("GITHUB_TOKEN",          regex.compile(r"\bgh[pous]_[A-Za-z0-9]{20,}\b")),
    ("GOOGLE_API_KEY",        regex.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b")),
    ("AWS_ACCESS_KEY_ID",     regex.compile(r"\bA[KS]IA[0-9A-Z]{16}\b")),
    ("AWS_SECRET_ACCESS_KEY", regex.compile(r"(?i)(aws[_\s-]*secret[_\s-]*access[_\s-]*key\s*[:=]\s*)([A-Za-z0-9/+=]{40})")),
    ("STRIPE_SK",             regex.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("SLACK_TOKEN",           regex.compile(r"\bxox(?:p|b|o|a)-[A-Za-z0-9-]{10,}\b")),
    ("BEARER_TOKEN",          regex.compile(r"(?i)\bBearer\s+([A-Za-z0-9\-\._=]+)")),
    ("GENERIC_SECRET",        regex.compile(r"(?i)\b(api[_\s-]?key|secret|token)\b\s*[:=]\s*([A-Za-z0-9\-_\/+=]{16,})")),
    ("PASSWORD",              regex.compile(r"(?i)\b(pass(word)?|pwd)\b\s*[:=]\s*([^\s'\"`]+)")),
]

EMAIL_RE      = regex.compile(r"\b([A-Z0-9._%+-]+)@([A-Z0-9.-]+\.[A-Z]{2,})\b", regex.IGNORECASE)
PHONE_RE      = regex.compile(r"(?<!\w)(\+?\d[\d\-\s().]{7,}\d)(?!\w)")
PEM_RE        = regex.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", regex.DOTALL)
URL_SECRET_RE = regex.compile(r"(?i)([?&])(token|access_token|id_token|auth|signature|key|code)=([A-Za-z0-9\.\-_/%+=]+)")

def redact_text(text: str):
    counts, samples = {}, {}
    def log(kind, original):
        counts[kind] = counts.get(kind, 0) + 1
        bucket = samples.setdefault(kind, [])
        h = sha8(original if isinstance(original, str) else json.dumps(original, ensure_ascii=False))
        if len(bucket) < 3:
            bucket.append(h)

    # 1) Private keys
    text = PEM_RE.sub(lambda m: (log("PRIVATE_KEY_PEM", "BLOCK") or "[REDACTED:PRIVATE_KEY_PEM]"), text)

    # 2) URL query secrets
    def url_sub(m):
        prefix, key, val = m.group(1), m.group(2), m.group(3)
        log("URL_QUERY_SECRET", f"{key}={val}")
        return f"{prefix}{key}=[REDACTED:URL_QUERY_SECRET hash:{sha8(val)}]"
    text = URL_SECRET_RE.sub(url_sub, text)

    # 3) Labeled/known tokens/keys/passwords
    def generic_sub_factory(kind, rgx):
        def _sub(m):
            if m.lastindex and m.lastindex >= 2:
                label = m.group(1) if m.group(1) else ""
                val   = m.group(m.lastindex)
                log(kind, val)
                return f"{label}[REDACTED:{kind} hash:{sha8(val)}]"
            full = m.group(0)
            log(kind, full)
            return f"[REDACTED:{kind} hash:{sha8(full)}]"
        return _sub

    for kind, rgx in PATTERNS:
        text = rgx.sub(generic_sub_factory(kind, rgx), text)

    # 4) Emails
    def email_sub(m):
        local, domain = m.group(1), m.group(2)
        masked_local = local[0] + "***" + (local[-1] if len(local) > 1 else "")
        original = m.group(0)
        log("EMAIL", original)
        return f"{masked_local}@{domain}"
    text = EMAIL_RE.sub(email_sub, text)

    # 5) Phones
    def phone_sub(m):
        s = m.group(1)
        digits = re.sub(r"\D", "", s)
        if len(digits) < 7: return s
        log("PHONE", s)
        n = len(digits); start_keep, end_keep = 2, 2
        masked_digits = digits[:start_keep] + "•"*max(4, n-start_keep-end_keep) + digits[-end_keep:]
        return f"[REDACTED:PHONE {masked_digits}]"
    text = PHONE_RE.sub(phone_sub, text)

    return text, {"counts": counts, "sample_hashes": samples}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="in_path",  required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    ap.add_argument("--log", dest="log_path", default=None)
    args = ap.parse_args()

    with open(args.in_path, "r", encoding="utf-8", errors="replace") as f:
        original = f.read()

    cleaned, meta = redact_text(original)

    with open(args.out_path, "w", encoding="utf-8") as f:
        f.write(cleaned)

    if args.log_path:
        with open(args.log_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    print("Redaction complete.")
    print("Sanitized:", args.out_path)
    print("Summary:", json.dumps(meta.get("counts", {}), indent=2))

if __name__ == "__main__":
    main()
