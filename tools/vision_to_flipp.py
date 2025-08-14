# tools/vision_to_flipp.py
import argparse, json, sys
from typing import List, Dict

from tools.vision_identify import identify_product  # must exist in your repo
from tools.flipp_adapter import search_deals

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="Path or URL to product photo")
    ap.add_argument("--postal", required=True, help="Postal code, e.g., M5V2T6")
    ap.add_argument("--country", default="CA", choices=["CA","US"])
    ap.add_argument("--max", type=int, default=8)
    args = ap.parse_args()

    print("Identifying product from image...")
    name = identify_product(args.image)
    if not name:
        print("Could not identify product from image.")
        sys.exit(2)
    print("Vision name:", name)

    print("Searching Flipp for deals...")
    deals: List[Dict] = search_deals(query=name, postal=args.postal, country=args.country, limit=args.max)
    if not deals:
        print("No deals found.")
        sys.exit(3)

    print("\nTop matches:")
    for d in deals:
        print(json.dumps(d, ensure_ascii=False, indent=2))

    best = deals[0]
    print("\nBEST:")
    print(f"  {best['title']} — ${best['price']} at {best['store']}")
    if best.get("flyer_url"):
        print(f"  Proof: {best['flyer_url']}")

if __name__ == "__main__":
    main()
