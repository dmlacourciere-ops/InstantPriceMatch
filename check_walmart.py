# check_walmart.py — quick UPC smoke test for Walmart provider
# Usage:
#   python check_walmart.py --upc 0064100136908 --country CA

import argparse
from pprint import pprint

from providers.walmart_playwright import get_offers_by_upc

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upc", required=True, help="UPC/EAN (string of digits)")
    ap.add_argument("--country", default="CA", choices=["CA", "US"])
    args = ap.parse_args()

    offers = get_offers_by_upc(args.upc, args.country)
    if not offers:
        print("No offers found.")
        return

    print("Offers:")
    for off in offers:
        pprint(off)

    cheapest = min(offers, key=lambda o: float(o["price"]))
    print("\nCheapest:")
    pprint(cheapest)

if __name__ == "__main__":
    main()
