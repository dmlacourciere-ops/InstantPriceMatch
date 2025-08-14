# tools/bundle_from_proofs.py
# Build a single cashier-ready PDF from your saved proof images.
# Safe-by-default: won't crash if folders are missing or empty.

import os
import sys
from datetime import datetime
from typing import List, Tuple

try:
    from fpdf import FPDF
    from PIL import Image
except Exception as e:
    print("[error] Missing libs. In your .venv run: pip install fpdf2 pillow")
    sys.exit(1)

# Paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .. from tools/
PROOFS_DIR   = os.path.join(PROJECT_ROOT, "proofs")
OUT_DIR      = os.path.join(PROJECT_ROOT, "bundles")
VALID_EXT    = {".png", ".jpg", ".jpeg", ".webp"}

def _list_proofs() -> List[Tuple[str, float]]:
    if not os.path.isdir(PROOFS_DIR):
        return []
    files = []
    for name in os.listdir(PROOFS_DIR):
        p = os.path.join(PROOFS_DIR, name)
        if os.path.isfile(p) and os.path.splitext(name)[1].lower() in VALID_EXT:
            try:
                ts = os.path.getmtime(p)
            except OSError:
                continue
            files.append((p, ts))
    files.sort(key=lambda x: x[1], reverse=True)
    return files

def _human(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

def _add_cover(pdf: FPDF, count: int):
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "Instant Price Match — Proof Bundle", ln=1, align="C")

    pdf.set_font("Helvetica", "", 12)
    pdf.ln(6)
    pdf.cell(0, 8, f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=1, align="C")
    pdf.cell(0, 8, f"Items included: {count}", ln=1, align="C")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6,
        "This document bundles your proof images. Each page contains one proof. "
        "Check sizes/dates match the store policy before checkout."
    )

def _add_image_page(pdf: FPDF, img_path: str, caption: str):
    pdf.add_page()
    page_w, page_h = pdf.w, pdf.h
    margin = 10
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, caption, ln=1)
    y = pdf.get_y() + 3
    avail_w = page_w - 2 * margin
    avail_h = page_h - y - margin
    try:
        with Image.open(img_path) as im:
            im_w, im_h = im.size
    except Exception:
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(200, 0, 0)
        pdf.multi_cell(0, 6, f"[warn] Could not open image: {img_path}")
        pdf.set_text_color(0, 0, 0)
        return
    scale = min(avail_w / im_w, avail_h / im_h)
    w, h = im_w * scale, im_h * scale
    x = (page_w - w) / 2
    try:
        pdf.image(img_path, x=x, y=y, w=w, h=h)
    except Exception:
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(200, 0, 0)
        pdf.multi_cell(0, 6, f"[warn] Failed to place image: {img_path}")
        pdf.set_text_color(0, 0, 0)

def main():
    proofs = _list_proofs()
    if not proofs:
        print(f"[error] No proof images found. Generate some via app menu 3 or 1, then re-run.")
        print(f"[hint] Expected folder: {PROOFS_DIR}")
        sys.exit(2)

    print("\nRecent proof images (newest first):")
    for i, (p, ts) in enumerate(proofs[:20], start=1):
        print(f" {i:>2}) {os.path.basename(p)}    { _human(ts) }")

    print("\nHow many to include?")
    print(" - Type a number (e.g. 5) for that many newest")
    print(" - Type 'all' to include everything")
    sel = (input("Your choice [5]: ").strip().lower() or "5")

    chosen = proofs
    if sel != "all":
        try:
            n = max(1, int(sel))
            chosen = proofs[:n]
        except ValueError:
            chosen = proofs[:5]

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"bundle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=10)

    _add_cover(pdf, count=len(chosen))
    for p, ts in chosen:
        caption = f"{os.path.basename(p)}    ({_human(ts)})"
        _add_image_page(pdf, p, caption)

    try:
        pdf.output(out_path)
    except Exception as e:
        print(f"[error] Failed to write PDF: {e}")
        sys.exit(3)

    print(f"\n[ok] Saved bundle: {out_path}")
    print("[tip] Open with: start \"\" \"" + out_path + "\"  (PowerShell)")

if __name__ == "__main__":
    main()
