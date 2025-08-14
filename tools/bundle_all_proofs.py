from pathlib import Path
from datetime import datetime
from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
PROOFS_DIR = ROOT / "proofs"
BUNDLES_DIR = ROOT / "bundles"
BUNDLES_DIR.mkdir(exist_ok=True)

out = BUNDLES_DIR / f"all_proofs_{datetime.now():%Y%m%d_%H%M%S}.pdf"

files = sorted(PROOFS_DIR.glob("proof_*.png"), key=lambda p: p.stat().st_mtime)
print(f"[info] bundling {len(files)} proofs -> {out}")

pdf = FPDF(unit="pt", format="Letter")
pdf.set_margins(36, 36, 36)

pdf.add_page()
pdf.set_font("Helvetica", "B", 20)
pdf.cell(0, 28, "Instant Price Match - All Proofs", ln=1)
pdf.set_font("Helvetica", "", 12)
pdf.cell(0, 18, f"Generated: {datetime.now():%Y-%m-%d %H:%M}", ln=1)
pdf.cell(0, 18, f"Items: {len(files)}", ln=1)

for p in files:
    pdf.add_page()
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 14, f"{p.name}    {datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M:%S}", ln=1)
    pdf.image(str(p), x=pdf.l_margin, y=pdf.get_y()+6,
              w=pdf.w - pdf.l_margin - pdf.r_margin)

pdf.output(str(out))
print("[done]", out)
