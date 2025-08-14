# tools/vision_identify.py
# Vision-based product identifier -> normalized JSON dict
# Works with OpenAI chat.completions (vision models). CLI-friendly.

from __future__ import annotations

import os
import io
import json
import base64
import argparse
import mimetypes
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen
from urllib.parse import urlparse

# ---- OpenAI client (>=1.0 library)
try:
    from openai import OpenAI  # type: ignore
except Exception:
    # Back-compat if the import path changes; fail clearly later if missing
    OpenAI = None  # type: ignore

# Choose a vision-capable chat model you have access to
MODEL_NAME = os.getenv("VISION_MODEL", "gpt-4o-mini")

# ---------- small helpers ----------

def _is_url(s: str) -> bool:
    try:
        u = urlparse(s)
        return u.scheme in ("http", "https")
    except Exception:
        return False

def _guess_mime(path_or_url: str) -> str:
    mt, _ = mimetypes.guess_type(path_or_url)
    return mt or "image/jpeg"

def _url_to_data_url(url: str, timeout: int = 15) -> str:
    req = Request(url, headers={"User-Agent": "InstantPriceMatch/vision-identify"})
    with urlopen(req, timeout=timeout) as r:  # nosec - dev tool use
        data = r.read()
        mime = r.headers.get_content_type() or _guess_mime(url)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"

def _file_to_data_url(path: str) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image not found: {path}")
    mime = _guess_mime(path)
    with open(path, "rb") as f:
        b = f.read()
    b64 = base64.b64encode(b).decode("ascii")
    return f"data:{mime};base64,{b64}"

def _image_to_data_url(value: str) -> str:
    if value.startswith("data:"):
        return value
    return _url_to_data_url(value) if _is_url(value) else _file_to_data_url(value)

def _to_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, (int, float)):
        return str(x)
    return str(x).strip()

def _norm_confidence(x: Any) -> float:
    # Accept numbers, numeric strings, or labels like "high"/"medium"/"low"
    if isinstance(x, (int, float)):
        try:
            return max(0.0, min(1.0, float(x)))
        except Exception:
            return 0.0
    if isinstance(x, str):
        s = x.strip().lower()
        # numeric string
        if s.replace(".", "", 1).isdigit():
            try:
                return max(0.0, min(1.0, float(s)))
            except Exception:
                return 0.0
        # label mapping
        mapping = {
            "very high": 0.95,
            "high": 0.90,
            "med": 0.6,
            "medium": 0.6,
            "low": 0.3,
            "very low": 0.15,
            "unknown": 0.0,
        }
        return mapping.get(s, 0.0)
    return 0.0

def _strip_json_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # remove leading ```json / ``` and trailing ```
        first_new = s.find("\n")
        if first_new != -1:
            s = s[first_new + 1 :]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()

def _json_coerce(s: str) -> Dict[str, Any]:
    """Try hard to pull a JSON object from a model reply."""
    txt = _strip_json_fences(s)
    try:
        return json.loads(txt)
    except Exception:
        # heuristic: grab the largest {...} span
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(txt[start : end + 1])
            except Exception:
                pass
    return {}

# ---------- main function ----------

def identify_product(
    image: str,
    country_hint: Optional[str] = None,
    api_key: Optional[str] = None,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    image: path/url/data: url
    returns normalized dict:
      brand, name, variant, size_text, possible_upc, confidence(float 0..1), notes, strategy
    """
    if OpenAI is None:
        raise RuntimeError("openai python package is not installed. pip install openai")

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing. Set env var or pass --api-key.")

    data_url = _image_to_data_url(image)

    client = OpenAI(api_key=key)

    sys_prompt = (
        "You are a retail product identifier. "
        "Given a single product photo, output a compact JSON object with fields:\n"
        '  brand (string), name (string), variant (string), '
        '  size_text (string like \"284 mL\" or \"10.5 oz\" if visible else \"\"), '
        '  possible_upc (digits only if readable else \"\"), '
        '  confidence (one of: \"very high\",\"high\",\"medium\",\"low\" or a number 0–1), '
        "  notes (very short).\n"
        "If multiple products are visible, choose the dominant/foreground retail item. "
        "Prefer exact label text when visible. Do not invent UPCs."
    )
    if country_hint:
        sys_prompt += f" The shopper is in country code: {country_hint}. Prefer that locale."

    user_instr = (
        "Return only a JSON object. No markdown, no commentary. "
        "If size is readable on the label, include it in size_text. "
        "If UPC digits are readable, provide them in possible_upc (digits only)."
    )

    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_instr},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.2,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        if debug:
            print(f"MODEL ERROR: {e}")
        raw = "{}"

    data = _json_coerce(raw)

    if debug:
        print("=== RAW MODEL OUTPUT ===")
        try:
            print(json.dumps(data if data else raw, indent=4, ensure_ascii=False))
        except Exception:
            print(raw)
        print("========================")

    out = {
        "brand": _to_str(data.get("brand")) if isinstance(data, dict) else "",
        "name": _to_str(data.get("name")) if isinstance(data, dict) else "",
        "variant": _to_str(data.get("variant")) if isinstance(data, dict) else "",
        "size_text": _to_str(data.get("size_text")) if isinstance(data, dict) else "",
        "possible_upc": _to_str(data.get("possible_upc")) if isinstance(data, dict) else "",
        "confidence": _norm_confidence(data.get("confidence")) if isinstance(data, dict) else 0.0,
        "notes": _to_str(data.get("notes")) if isinstance(data, dict) else "",
        "strategy": "vision",
    }
    return out

# ---------- CLI ----------

def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Identify retail product from an image using OpenAI vision.")
    p.add_argument("--image", required=True, help="Path, http(s) URL, or data: URL")
    p.add_argument("--country", dest="country", default=None, help="Optional ISO country hint (e.g., CA, US)")
    p.add_argument("--api-key", dest="api_key", default=None, help="Override OPENAI_API_KEY")
    p.add_argument("--debug", action="store_true", help="Print raw model JSON")
    return p

if __name__ == "__main__":
    args = _build_cli().parse_args()
    out = identify_product(args.image, country_hint=args.country, api_key=args.api_key, debug=args.debug)
    print(json.dumps(out, ensure_ascii=False, indent=2))
