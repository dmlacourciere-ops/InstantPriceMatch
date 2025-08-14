import requests
from typing import List, Dict

HEADERS = {
    "User-Agent": "InstantPriceMatch/0.1 (+https://example.local)"
}

def name_to_upc_candidates(name: str, max_results: int = 6) -> List[Dict]:
    """
    Returns a list of candidate products from OpenFoodFacts with fields:
      - code (UPC/EAN)
      - product_name
      - brands
      - quantity
    """
    url = "https://world.openfoodfacts.org/cgi/search.pl"
    params = {
        "search_terms": name,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": max_results
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        js = r.json()
        out: List[Dict] = []
        for p in js.get("products", []):
            code = p.get("code")
            pname = p.get("product_name") or ""
            brand = p.get("brands") or ""
            qty = p.get("quantity") or ""
            if code and pname:
                out.append({
                    "code": str(code),
                    "product_name": pname.strip(),
                    "brands": brand.strip(),
                    "quantity": qty.strip()
                })
        return out
    except Exception as e:
        print(f"[OFF] name_to_upc_candidates failed: {e}")
        return []
