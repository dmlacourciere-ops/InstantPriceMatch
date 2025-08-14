# tools/flipp_adapter.py
# Adapter to query Canadian flyers via your providers.flipp_provider module.
# Normalizes to: {store, title, price, url, image, upc}

import importlib
import inspect
import math
import os
import re
import sys
from typing import Any, Dict, List, Optional

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TOOLS_DIR)
PROVIDERS_DIR = os.path.join(ROOT_DIR, "providers")
for p in (ROOT_DIR, PROVIDERS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

def _import_flipp():
    for name in ("flipp_provider", "providers.flipp_provider"):
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None

def _price_to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            if math.isnan(v):  # type: ignore[arg-type]
                return None
        except Exception:
            pass
        return float(v)
    s = str(v)
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", s.replace(",", ""))
    return float(m.group(1)) if m else None

def _first_callable(mod, names: List[str]):
    for n in names:
        f = getattr(mod, n, None)
        if callable(f):
            return f
    return None

def _norm_item(x: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(x, dict):
        return None
    title = x.get("title") or x.get("name") or x.get("product") or x.get("description") or ""
    url = x.get("url") or x.get("link") or ""
    upc = x.get("upc") or ""
    price = _price_to_float(x.get("price") or x.get("current_price") or x.get("sale_price"))
    # Flipp often has merchant/store and an image
    store = x.get("store") or x.get("merchant") or x.get("merchant_name") or x.get("retailer") or ""
    image = x.get("image") or x.get("image_url") or x.get("flyer_image") or ""
    return {
        "store": str(store).strip(),
        "title": str(title).strip(),
        "price": price,
        "url": str(url).strip(),
        "upc": str(upc).strip(),
        "image": str(image).strip(),
    }

def _to_list(res: Any) -> List[Dict[str, Any]]:
    if res is None:
        return []
    if isinstance(res, list):
        return [r for r in (_norm_item(it) for it in res) if r]
    if isinstance(res, dict):
        one = _norm_item(res)
        return [one] if one else []
    return []

def lookup_by_text(name: Optional[str]) -> List[Dict[str, Any]]:
    """
    Query Flipp by text (best effort). We try common function names:
    - search(name=...), by_name(...), query(...), search_items(...)
    """
    mod = _import_flipp()
    if mod is None or not name:
        return []
    f = _first_callable(mod, ["search", "by_name", "lookup_by_name", "query", "search_items"])
    if not f:
        return []
    # Try positional then keyword calls
    try:
        res = f(name)
    except TypeError:
        res = None
        for kw in ("name", "query", "search", "text"):
            try:
                res = f(**{kw: name})
                break
            except TypeError:
                continue
            except Exception:
                res = None
                break
    except Exception:
        res = None
    return _to_list(res)

def lookup(upc: Optional[str], name: Optional[str]) -> List[Dict[str, Any]]:
    """
    Flipp is text-centric. We'll try text lookup; if UPC is present and your
    provider supports it, we pass it as a text hint too.
    """
    query = name or upc or None
    return lookup_by_text(query)
