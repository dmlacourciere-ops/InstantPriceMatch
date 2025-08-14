import argparse
from datetime import datetime
from pathlib import Path
import json
from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
PROOFS_DIR = ROOT / "proofs"
DATA_DIR = ROOT / "data"
POLICY_FILE = DATA_DIR / "policies.json"

# Replace/strip characters FPDF (latin-1) can't encode
def safe_text(s: str) -> str:
    if not s:
        return ""
    rep = {
        "•": "- ",
        "–": "-",
        "—": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "™": "(TM)",
        "…": "...",
        "\u00a0": " "  # non-breaking space
    }
    for k, v in rep.items():
        s = s.replace(k, v)
    try:
        s.encode("latin-1")
        return s
    except UnicodeEncodeError:
        # Drop any remaining unsupported chars
        return s.encode("latin-1", "ignore").decode("latin-1")

def _ensure_dirs():
    PROOFS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

def _load_policies():
    if POLICY_FILE.exists():
        try:
            return json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def make_pdf(
    store: str,
    price: str,
    item: str,
    upc: str = "",
    valid_from: str = "",
    valid_to: str = "",
    url: str = "",
    product_image: str = "",
    policy_key: str = "",
    cashier_note: str = "",
):
    _ensure_dirs()
    policies = _load_policies()
    policy = policies.get((policy_key or store or "").lower(), {})

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_name = (
        f"{store}_{item}_{price}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        .replace(" ", "_").replace("/", "-").replace("\\", "-")
    )
    out_path = PROOFS_DIR / f"price_match_proof_{safe_name}.pdf"

    pdf = FPDF(unit="mm", format="Letter")  # 216 x 279 mm
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_title("Price Match Proof")

    # Header
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Price Match Proof", ln=1)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generated: {ts}", ln=1)
    pdf.ln(2)

    # Core block
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(40, 8, "Store:", border=0)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, safe_text(store), ln=1)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(40, 8, "Item:", border=0)
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 7, safe_text(item))

    if upc:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(40, 8, "UPC:", border=0)
        pdf.set_font("Helvetica", "", 12)
        pdf.cell(0, 8, safe_text(upc), ln=1)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(40, 8, "Price (CAD):", border=0)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, safe_text(price), ln=1)

    if valid_from or valid_to:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(40, 8, "Valid Dates:", border=0)
        pdf.set_font("Helvetica", "", 12)
        vf = valid_from or "-"
        vt = valid_to or "-"
        pdf.cell(0, 8, f"{safe_text(vf)} to {safe_text(vt)}", ln=1)

    if url:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, "Offer/Source URL:", ln=1)
        pdf.set_font("Helvetica", "", 11)
        # Clickable link plus visible text
        vis = safe_text(url)
        pdf.set_text_color(0, 0, 255)
        pdf.write(6, vis, url)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(8)

    # Optional product image
    if product_image:
        try:
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 7, "Product Image:", ln=1)
            pdf.image(product_image, w=70)
            pdf.ln(4)
        except Exception:
            pass  # image is optional

    # Cashier note / policy hint
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Cashier Note:", ln=1)
    pdf.set_font("Helvetica", "", 11)
    note = (cashier_note or "").strip()
    if not note:
        default_note = (
            policy.get("cashier_note")
            or "Please verify identical item, size/variant, and that the offer is current and in stock per store policy."
        )
        note = default_note
    pdf.multi_cell(0, 6, safe_text(note))

    if policy:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, "Policy Snapshot:", ln=1)
        pdf.set_font("Helvetica", "", 10)
        for b in policy.get("bullets", []):
            pdf.multi_cell(0, 5, safe_text(f"- {b}"))

    # Footer
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, "This document is generated to assist with in-store price matching. Details should be verified at point of sale.")

    pdf.output(str(out_path))
    return str(out_path)

def parse_args():
    p = argparse.ArgumentParser(description="Generate a cashier-friendly Price Match Proof PDF.")
    p.add_argument("--store", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--item", required=True)
    p.add_argument("--upc", default="")
    p.add_argument("--valid-from", default="")
    p.add_argument("--valid-to", default="")
    p.add_argument("--url", default="")
    p.add_argument("--image", default="")
    p.add_argument("--policy", default="")
    p.add_argument("--cashier-note", default="")
    return p.parse_args()

def main():
    args = parse_args()
    out = make_pdf(
        store=args.store,
        price=args.price,
        item=args.item,
        upc=args.upc,
        valid_from=args.valid_from,
        valid_to=args.valid_to,
        url=args.url,
        product_image=args.image,
        policy_key=args.policy,
        cashier_note=args.cashier_note,
    )
    print(out)

if __name__ == "__main__":
    main()
