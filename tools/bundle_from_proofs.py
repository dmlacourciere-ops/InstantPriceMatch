# tools/bundle_from_proofs.py
# Creates a single PDF bundle from your recent proof images.
# Fail-safes:
# - Uses a Windows TTF (Arial/Segoe/Calibri) for Unicode. Falls back to Helvetica + ASCII if needed.
# - Skips unreadable images instead of crashing.
# - Creates output folder if missing.

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROOFS_DIR = PROJECT_ROOT / "proofs"
BUNDLES_DIR = PROJECT_ROOT / "bundles"
BUNDLES_DIR.mkdir(parents=True, exist_ok=True)

# Candidate fonts for Unicode support (Windows)
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
]

TITLE = "Instant Price Match — Proof Bundle"
SUBTITLE = "Generated: {now}"
FOOTER = "Cashier: verify flyer dates + product details. Prices are subject to store policy."

def find_unicode_font() -> str | None:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None

class Pdf(FPDF):
    def __init__(self):
        super().__init__(unit="mm", format="Letter")  # 8.5x11
        self.set_auto_page_break(auto=True, margin=12)
        self.unicode_ready = False

    def setup_font(self):
        """Try to load a Unicode TTF; fall back to core fonts if not found."""
        font_path = find_unicode_font()
        if font_path:
            try:
                self.add_font("U", "", font_path, uni=True)
                self.set_font("U", size=14)
                self.unicode_ready = True
                return
            except Exception as e:
                print(f"[warn] failed to load unicode font at {font_path}: {e}")

        # Fallback to core font (ASCII-only)
        self.set_font("Helvetica", size=14)
        self.unicode_ready = False

    def safe_text(self, text: str) -> str:
        """If Unicode font unavailable, strip/replace problematic chars."""
        if self.unicode_ready:
            return text
        # replace em dash and other common symbols with ASCII equivalents
        replacements = {
            "—": "-",
            "–": "-",
            "•": "*",
            "™": "(TM)",
            "®": "(R)",
            "’": "'",
            "“": '"',
            "”": '"',
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
        # also drop anything still non-ascii
        return text.encode("ascii", errors="ignore").decode("ascii")

def list_proofs(limit: int | None = None) -> List[Path]:
    if not PROOFS_DIR.exists():
        return []
    items = sorted(PROOFS_DIR.glob("proof_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    if limit is not None:
        items = items[:limit]
    return items

def human_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

def add_cover(pdf: Pdf, count: int):
    pdf.add_page()
    pdf.setup_font()

    pdf.set_font(size=20)
    pdf.cell(0, 16, pdf.safe_text(TITLE), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font(size=12)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf.cell(0, 8, pdf.safe_text(SUBTITLE.format(now=now)), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(4)
    pdf.cell(0, 8, pdf.safe_text(f"Included proofs: {count}"), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(10)
    pdf.set_font(size=10)
    pdf.multi_cell(0, 6, pdf.safe_text(FOOTER))

def add_image_page(pdf: Pdf, img_path: Path):
    pdf.add_page()
    pdf.setup_font()

    # Header line with file name and timestamp
    ts = img_path.stat().st_mtime
    header = f"{img_path.name} — {human_time(ts)}"
    pdf.set_font(size=11)
    pdf.cell(0, 8, pdf.safe_text(header), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Fit image on page, keep aspect ratio, leave margins
    margin = 10
    max_w = pdf.w - 2 * margin
    max_h = pdf.h - 2 * margin - 10  # leave some room for header
    try:
        with Image.open(img_path) as im:
            w, h = im.size
            aspect = w / h if h else 1.0
    except Exception as e:
        pdf.set_text_color(200, 0, 0)
        pdf.multi_cell(0, 6, pdf.safe_text(f"[error] could not open image: {img_path} ({e})"))
        pdf.set_text_color(0, 0, 0)
        return

    # compute target size
    target_w = max_w
    target_h = target_w / aspect
    if target_h > max_h:
        target_h = max_h
        target_w = target_h * aspect

    x = (pdf.w - target_w) / 2
    y = pdf.get_y() + 2
    try:
        pdf.image(str(img_path), x=x, y=y, w=target_w, h=target_h)
    except Exception as e:
        pdf.set_text_color(200, 0, 0)
        pdf.multi_cell(0, 6, pdf.safe_text(f"[error] failed to place image: {img_path} ({e})"))
        pdf.set_text_color(0, 0, 0)

def main():
    proofs = list_proofs()
    if not proofs:
        print("[info] no proofs found in:", PROOFS_DIR)
        print("Run the app to generate proofs first (menu 1/2/3).")
        sys.exit(0)

    # Show menu
    print("\nRecent proof images (newest first):")
    for i, p in enumerate(proofs[:20], start=1):
        print(f"{i:3}) {p.name:45} {human_time(p.stat().st_mtime)}")
    print("\nHow many to include?")
    print(" - Type a number (e.g. 5) for that many newest")
    print(" - Type 'all' to include everything")
    choice = input("Your choice [5]: ").strip().lower() or "5"

    if choice == "all":
        chosen = proofs
    else:
        try:
            n = int(choice)
        except ValueError:
            n = 5
        chosen = proofs[:max(1, n)]

    out_name = f"bundle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    out_path = BUNDLES_DIR / out_name

    pdf = Pdf()
    add_cover(pdf, count=len(chosen))

    added = 0
    for p in chosen:
        add_image_page(pdf, p)
        added += 1

    try:
        pdf.output(str(out_path))
    except Exception as e:
        print(f"[error] failed to write PDF: {e}")
        sys.exit(1)

    print(f"\n[done] saved: {out_path}")
    # Helpful hint to open folder in PowerShell: use 'ii' (Invoke-Item)
    print("[tip] Open the folder:", BUNDLES_DIR)

if __name__ == "__main__":
    main()
