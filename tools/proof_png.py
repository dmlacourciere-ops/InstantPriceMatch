# tools/proof_png.py
# Compose a single PNG that a cashier can accept:
# - left: your camera capture
# - right: flyer/product image (if available)
# - header & details: price, store, title, URL, timestamp

from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
import textwrap
import os
from datetime import datetime

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    # Try common Windows fonts, fall back to default bitmap font
    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()

def _open_img(path: Optional[str], max_wh: Tuple[int, int]) -> Optional[Image.Image]:
    if not path or not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGB")
        img.thumbnail(max_wh, Image.Resampling.LANCZOS)
        return img
    except Exception:
        return None

def _draw_wrapped(draw: ImageDraw.ImageDraw, text: str, xy: Tuple[int,int], width_px: int, font, fill=(20,20,20), leading=6):
    if not text:
        return 0
    # naive word wrap by character width estimate
    avg_char = font.getlength("A") or 10
    max_chars = max(8, int(width_px / max(1.0, avg_char)))
    lines = textwrap.wrap(text, width=max_chars)
    x, y = xy
    h = 0
    for line in lines:
        draw.text((x, y+h), line, font=font, fill=fill)
        h += font.size + leading
    return h

def make_proof_png(
    title: str,
    price_text: str,
    store: str,
    url: str,
    camera_path: str,
    flyer_path: Optional[str],
    out_path: str,
) -> str:
    W, H = 1200, 800
    pad = 18
    # canvas
    img = Image.new("RGB", (W, H), (250, 250, 250))
    draw = ImageDraw.Draw(img)

    # header
    head_h = 70
    draw.rectangle([(0,0), (W, head_h)], fill=(15, 23, 42))
    title_font = _load_font(28)
    small_font = _load_font(18)
    draw.text((pad, 20), "Instant Price Match – Proof", font=title_font, fill=(255,255,255))
    draw.text((W-380, 24), datetime.now().strftime("%Y-%m-%d %H:%M"), font=small_font, fill=(220,220,220))

    # image slots
    left_box = (pad, head_h + pad, W//2 - pad, H - 220)
    right_box = (W//2 + pad, head_h + pad, W - pad, H - 220)
    draw.rectangle(left_box, outline=(210,210,210), width=2)
    draw.rectangle(right_box, outline=(210,210,210), width=2)

    cam = _open_img(camera_path, (left_box[2]-left_box[0]-8, left_box[3]-left_box[1]-8))
    if cam:
        img.paste(cam, (left_box[0]+4, left_box[1]+4))
    fly = _open_img(flyer_path, (right_box[2]-right_box[0]-8, right_box[3]-right_box[1]-8))
    if fly:
        img.paste(fly, (right_box[0]+4, right_box[1]+4))

    # details panel
    y = H - 205
    draw.rectangle([(pad, y-10), (W-pad, H-pad)], fill=(255,255,255), outline=(220,220,220), width=2)

    label_font = _load_font(20)
    value_font = _load_font(24)

    # Title (wrap)
    y += _draw_wrapped(draw, f"{title}", (pad+10, y), W - 2*pad - 20, value_font, fill=(15,15,15), leading=4) + 2

    # Price & store
    price_line = f"Best Price: {price_text} @ {store}" if store else f"Best Price: {price_text}"
    draw.text((pad+10, y), price_line, font=value_font, fill=(0, 122, 70))
    y += value_font.size + 8

    # URL
    if url:
        draw.text((pad+10, y), f"URL: {url}", font=label_font, fill=(30, 64, 175))
        y += label_font.size + 4

    # footer
    draw.text((pad+10, H-pad-26), "Show this image to the cashier for a price match.", font=small_font, fill=(70,70,70))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, format="PNG", optimize=True)
    return out_path
