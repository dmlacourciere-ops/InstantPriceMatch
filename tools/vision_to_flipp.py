# tools/vision_to_flipp.py
# Run EITHER of these from the project root:
#   python -m tools.vision_to_flipp --image "<path or URL>" --postal "M5V2T6"
#   python tools\vision_to_flipp.py --image "<path or URL>" --postal "M5V2T6"

import argparse, json, sys, os
from typing import List, Dict

# --- Import shim so this works as a module or a script ---
try:
    # Preferred when run with: python -m tools.vision_to_flipp
    from tools.vision_identify import identify_product
    from tools.flipp_adapter import search_deals
except Exception:
    # Fallback for: python tools\vision_to_flipp.py
    HERE = os.path.dirname(os.path.abspath(__file__))      # ...\InstantPriceMatch\tools
    ROOT = os.path.dirname(HERE)                           # ...\InstantPriceMatch
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from tools.vision_identify import identify_product
    from tools.flipp_adapter import search_deals

def _normalize_name(n):
    if isinstance(n, str):
        return n.strip()
    if isinstance(n, dict):
        # Be tolerant if identify_product returns a dict
        for k in ("name", "title", "product", "label"):
            v = n.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="Path or URL to product photo")
    ap.add_argument("--postal", required=True, help="Postal code, e.g., M5V2T6")
    ap.add_argument("--country", default="CA", choices=["CA","US"])
    ap.add_argument("--max", type=int, default=8)
    args = ap.parse_args()

    print("Identifying product from image...")
    try:
        raw = identify_product(args.image)
    except Exception as e:
        print("[ERROR] Vision identify failed:", repr(e))
        sys.exit(1)

    name = _normalize_name(raw)
    if not name:
        print("Could not identify product from image.")
        sys.exit(2)
    print("Vision name:", name)

    print("Searching Flipp for deals...")
    try:
        deals: List[Dict] = search_deals(query=name, postal=args.postal, country=args.country, limit=args.max)
    except Exception as e:
        print("[ERROR] Flipp search failed:", repr(e))
        sys.exit(3)

    if not deals:
        print("No deals found.")
        sys.exit(4)

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
