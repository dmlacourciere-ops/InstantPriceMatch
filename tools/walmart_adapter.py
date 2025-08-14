import importlib
import inspect
import math
import os
import re
import sys
from typing import Any, Dict, List, Optional

# Ensure project root and providers/ are importable
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TOOLS_DIR)
PROVIDERS_DIR = os.path.join(ROOT_DIR, "providers")
for p in (ROOT_DIR, PROVIDERS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

def _import_walmart_module():
    for name in ("walmart_playwright", "providers.walmart_playwright"):
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

def _normalize_item(x: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(x, dict):
        return None
    title = x.get("title") or x.get("name") or x.get("product_name") or x.get("description") or ""
    url = x.get("url") or x.get("product_url") or x.get("link") or ""
    upc = x.get("upc") or x.get("barcode") or x.get("ean") or ""
    price = _price_to_float(x.get("price") or x.get("current_price") or x.get("salePrice") or x.get("offer_price"))
    return {
        "store": "walmart",
        "title": str(title).strip(),
        "price": price,
        "url": str(url).strip(),
        "upc": str(upc).strip(),
    }

def _normalize_to_list(res: Any) -> List[Dict[str, Any]]:
    if res is None:
        return []
    if isinstance(res, list):
        return [r for r in (_normalize_item(it) for it in res) if r]
    if isinstance(res, dict):
        one = _normalize_item(res)
        return [one] if one else []
    return []  # unsupported shape

def lookup_by_upc_or_name(upc: Optional[str] = None, name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Compatibility layer. Supports:
      - separate UPC or name functions
      - a single-argument function like walmart_lookup_playwright(upc_or_name: str) -> Optional[Dict]
    Normalizes all outputs to a list of {title, price, url, upc}.
    """
    mod = _import_walmart_module()
    if mod is None:
        return []

    f_upc  = _first_callable(mod, ["lookup_by_upc", "by_upc", "lookup_upc", "get_by_upc"])
    f_name = _first_callable(mod, ["lookup_by_name", "search", "by_name", "lookup_name", "query"])
    f_both = _first_callable(mod, ["lookup_by_upc_or_name", "lookup", "find", "walmart_lookup_playwright"])

    # Prefer UPC if provided; otherwise use name
    query_str: Optional[str] = upc or name

    results: List[Dict[str, Any]] = []

    # 1) Dedicated UPC function
    if upc and f_upc:
        try:
            res = f_upc(upc)
        except TypeError:
            try:
                res = f_upc(upc=upc)
            except Exception:
                res = None
        except Exception:
            res = None
        results = _normalize_to_list(res)
        if results:
            return results

    # 2) Dedicated NAME function
    if name and f_name:
        try:
            res = f_name(name)
        except TypeError:
            # try common kwarg spellings
            res = None
            for kw in ("name", "query", "search"):
                try:
                    res = f_name(**{kw: name})
                    break
                except TypeError:
                    continue
                except Exception:
                    res = None
                    break
        except Exception:
            res = None
        results = _normalize_to_list(res)
        if results:
            return results

    # 3) Single-argument "both" function (e.g., walmart_lookup_playwright(upc_or_name))
    if f_both and query_str:
        # Detect if it takes exactly one positional parameter
        try:
            sig = inspect.signature(f_both)
            params = list(sig.parameters.values())
            takes_one_positional = (
                len(params) == 1 and
                params[0].kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            )
        except Exception:
            takes_one_positional = False

        res = None
        if takes_one_positional:
            try:
                res = f_both(query_str)
            except Exception:
                res = None
        else:
            # Try common kwarg names
            for kw in ("upc_or_name", "query", "name", "upc"):
                try:
                    res = f_both(**{kw: query_str})
                    break
                except TypeError:
                    continue
                except Exception:
                    res = None
                    break

        results = _normalize_to_list(res)
        if results:
            return results

    return []
