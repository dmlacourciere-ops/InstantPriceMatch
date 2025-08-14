# providers/upcitemdb_provider.py
# Free: 100 requests/day total (lookup+search combined).
# Docs: https://devs.upcitemdb.com/  (FREE plan uses /prod/trial, no key)
import requests
from typing import Optional, Dict, Any

BASE = "https://api.upcitemdb.com/prod/trial"

def lookup(upc: str, timeout: int = 20) -> Optional[Dict[str, Any]]:
    upc_digits = "".join(c for c in upc if c.isdigit())
    url = f"{BASE}/lookup?upc={upc_digits}"
    r = requests.get(url, timeout=timeout)
    if r.status_code != 200:
        return None
    j = r.json()
    items = j.get("items") or []
    if not items:
        return None
    it = items[0]
    return {
        "barcode": upc_digits,
        "product_name": it.get("title", ""),
        "brand": it.get("brand", ""),
        "quantity": it.get("size", "") or it.get("dimension", "") or "",
        "image_url": (it.get("images") or [None])[0],
        "source": "UPCItemDB (trial)"
    }
