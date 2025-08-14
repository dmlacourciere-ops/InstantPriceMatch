# proof.py
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import textwrap, os
from typing import List, Dict, Any

def _font(size: int):
    try: return ImageFont.truetype("arial.ttf", size)
    except: return ImageFont.load_default()

def make_proof(
    store: str,
    title: str,
    price: str,
    source_url: str,
    postal_code: str,
    valid_from: str = "",
    valid_to: str = "",
    out_dir: str = "proofs"
) -> str:
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    W, H = 900, 600
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    d.rectangle([0,0,W,90], fill=(20,110,255))
    d.text((30, 30), "Instant Price Match — Proof", fill="white", font=_font(32))

    d.text((30, 120), f"Store: {store}", fill="black", font=_font(30))
    d.text((30, 170), f"Price: {price}", fill="black", font=_font(30))

    wrap = textwrap.fill(title, width=50)
    d.text((30, 230), f"Item: {wrap}", fill="black", font=_font(28))

    if valid_from or valid_to:
        d.text((30, 330), f"Valid: {valid_from} → {valid_to}", fill="black", font=_font(24))

    d.text((30, 380), f"Source: {source_url[:90]}...", fill="black", font=_font(22))
    d.text((30, 420), f"Postal code: {postal_code}", fill="black", font=_font(22))
    d.text((30, 460), f"Generated: {now}", fill="black", font=_font(22))
    d.text((30, 520), "Show this at checkout to request a price match.", fill="black", font=_font(20))

    fname = f"proof_{store.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(out_dir, fname)
    img.save(path)
    return path

def make_bundle_pdf(items: List[Dict[str, Any]], postal_code: str, out_dir: str = "proofs") -> str:
    """
    items: list of {store,title,price,url,valid_from,valid_to,ts}
    Generates a multi-page PDF, one item per page.
    """
    os.makedirs(out_dir, exist_ok=True)
    pages = []
    W, H = 1240, 1754  # ~A4 @150dpi
    for it in items:
        img = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(img)
        d.rectangle([0,0,W,140], fill=(20,110,255))
        d.text((40, 50), "Instant Price Match — Bundle Proof", fill="white", font=_font(48))

        y = 180
        d.text((40, y), f"Store: {it.get('store','')}", fill="black", font=_font(40)); y+=60
        d.text((40, y), f"Price: {it.get('price','')}", fill="black", font=_font(40)); y+=60

        title = it.get("title","")
        for line in textwrap.wrap(f"Item: {title}", width=60):
            d.text((40, y), line, fill="black", font=_font(36)); y+=48

        vf, vt = it.get("valid_from",""), it.get("valid_to","")
        if vf or vt:
            d.text((40, y), f"Valid: {vf} → {vt}", fill="black", font=_font(30)); y+=44

        d.text((40, y), f"Source: {it.get('url','')}", fill="black", font=_font(28)); y+=44
        d.text((40, y), f"Postal code: {postal_code}", fill="black", font=_font(28)); y+=44
        d.text((40, y), f"Generated: {it.get('ts','')}", fill="black", font=_font(28)); y+=44

        d.text((40, H-80), "Show this PDF at checkout to request a price match for all items above.", fill="black", font=_font(26))
        pages.append(img)

    if not pages:
        raise RuntimeError("No items to include in bundle PDF.")

    fname = f"checkout_bundle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = os.path.join(out_dir, fname)
    pages[0].save(path, save_all=True, append_images=pages[1:], format="PDF")
    return path

# ADD THIS: Wrapper function that app.py expects
def generate_proof_png(output_dir: str, item_data: Dict[str, Any]) -> str:
    """
    Wrapper function for app.py compatibility.
    Converts the item_data format from app.py to what make_proof expects.
    """
    # Extract data from the format app.py provides
    store = item_data.get('retailer', 'Unknown Store')
    title = item_data.get('product_name', 'Unknown Product')
    price = f"${item_data.get('price_cad', 0):.2f}"
    source_url = item_data.get('url', '')
    
    # Use a default postal code - you might want to make this configurable
    postal_code = "N6A 3K7"  # London, ON default
    
    # Call the existing make_proof function
    return make_proof(
        store=store,
        title=title,
        price=price,
        source_url=source_url,
        postal_code=postal_code,
        out_dir=output_dir
    )