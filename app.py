# app.py — unified CLI for Instant Price Match
# Usage:
#   python app.py --upc 0064100136908 --country CA
# Prints one JSON object: {input, offers, cheapest, proof_path, errors}

import argparse, json, time
from pathlib import Path
from typing import Dict, Any, List, Optional

# Provider (Walmart — CA-focused right now)
from providers.walmart_playwright import get_offers_by_upc

from PIL import Image, ImageDraw, ImageFont

def make_proof(offer: Dict[str, Any], upc: str, country: str) -> str:
    """Create a simple PNG proof and return the saved file path."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    ymd = time.strftime("%Y-%m-%d")
    out_dir = Path("proofs") / ymd
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{upc}.png"

    img = Image.new("RGB", (1000, 600), color=(18, 18, 18))
    draw = ImageDraw.Draw(img)
    try:
        font_big = ImageFont.truetype("arial.ttf", 40)
        font = ImageFont.truetype("arial.ttf", 28)
        font_small = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font_big = font = font_small = ImageFont.load_default()

    draw.text((40, 40), "Instant Price Match — Proof", fill=(255, 255, 255), font=font_big)
    draw.text((40, 100), f"Store: {offer.get('store','?')}  Country: {country}", fill=(220, 220, 220), font=font)
    draw.text((40, 140), f"Product: {offer.get('title','(unknown)')}", fill=(220, 220, 220), font=font)
    draw.text((40, 180), f"UPC: {upc}", fill=(220, 220, 220), font=font)
    price_line = f"Price: {offer.get('currency','')} {offer.get('price','?')}"
    draw.text((40, 220), price_line, fill=(255, 220, 160), font=font)
    draw.text((40, 260), f"URL: {offer.get('url','')}", fill=(150, 200, 255), font=font_small)
    draw.text((40, 320), f"Generated: {ts}", fill=(180, 180, 180), font=font_small)

    img.save(out_path)
    return str(out_path)

def pick_cheapest(offers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best = None
    for o in offers:
        try:
            price = float(o.get("price"))
        except Exception:
            continue
        if best is None or price < float(best.get("price", 9e9)):
            best = o
    return best

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upc", type=str, required=True)
    ap.add_argument("--country", type=str, default="CA", choices=["CA", "US"])
    args = ap.parse_args()

    result = {
        "input": {"upc": args.upc, "country": args.country},
        "offers": [],
        "cheapest": None,
        "proof_path": None,
        "errors": []
    }

    try:
        offers = get_offers_by_upc(args.upc, args.country) or []
        result["offers"] = offers
    except Exception as e:
        result["errors"].append(f"Walmart error: {e!r}")

    cheapest = pick_cheapest(result["offers"])
    result["cheapest"] = cheapest

    if cheapest:
        try:
            result["proof_path"] = make_proof(cheapest, args.upc, args.country)
        except Exception as e:
            result["errors"].append(f"Proof error: {e!r}")

    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
