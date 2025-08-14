# providers/off_live.py
from typing import Optional, Dict, Any
import requests

OFF_SINGLE_API = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"

def fetch_off_product(barcode: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    """
    Live lookup from OpenFoodFacts by barcode.
    Returns {barcode, brand, product_name, quantity} or None.
    """
    b = "".join(ch for ch in barcode if ch.isdigit())
    if not b:
        return None
    try:
        r = requests.get(OFF_SINGLE_API.format(barcode=b), timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != 1:
            return None
        p = data.get("product", {}) or {}
        brand = ""
        if p.get("brands"):
            brand = str(p["brands"]).split(",")[0].strip()
        elif p.get("brand"):
            brand = str(p["brand"]).strip()

        out = {
            "barcode": b,
            "brand": brand,
            "product_name": p.get("product_name") or p.get("product_name_en") or p.get("generic_name_en") or "",
            "quantity": p.get("quantity") or "",
        }
        # Normalize empties
        for k in list(out.keys()):
            if out[k] is None:
                out[k] = ""
        return out
    except Exception:
        return None
