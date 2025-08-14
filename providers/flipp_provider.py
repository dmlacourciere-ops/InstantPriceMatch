# providers/flipp_provider.py
# Flipp (unofficial) flyer search with caching + resilient parsing.
# Queries by text + Canadian postal code.

import requests
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse
from util.cache import load_json, save_json

PRIMARY_URL = "https://backflipp.wishabi.com/flipp/items/search"
FALLBACK_URL = "https://backflipp.wishabi.com/flipp/items/search"  # keep same; some regions vary

HEADERS = {
    "User-Agent": "InstantPriceMatch/0.1 (+local dev)",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://flipp.com/",
    "Origin": "https://flipp.com",
    "Accept-Language": "en-CA,en;q=0.9",
    "Connection": "keep-alive",
}

# Map known domains to retailer names for inference when name is missing
DOMAIN_STORE_MAP = {
    "walmart.ca": "Walmart",
    "realcanadiansuperstore.ca": "Real Canadian Superstore",
    "loblaws.ca": "Loblaws",
    "nofrills.ca": "No Frills",
    "freshco.com": "FreshCo",
    "metro.ca": "Metro",
    "gianttiger.com": "Giant Tiger",
    "sobeys.com": "Sobeys",
    "foodbasics.ca": "Food Basics",
    "longos.com": "Longo's",
    "costco.ca": "Costco",
    "canadiantire.ca": "Canadian Tire",
    "shoppersdrugmart.ca": "Shoppers Drug Mart",
}

def _infer_store_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        for dom, name in DOMAIN_STORE_MAP.items():
            if dom in host:
                return name
    except Exception:
        pass
    return ""

def _pick_retailer(it: Dict[str, Any]) -> str:
    """Flipp returns merchant/store under many keys. Try them all."""
    for key in ("merchant", "retailer", "store", "merchant_info", "store_info"):
        val = it.get(key)
        if isinstance(val, dict):
            for name_key in ("name", "merchant_name", "store_name", "retailer_name", "brand_name"):
                name = val.get(name_key)
                if isinstance(name, str) and name.strip():
                    return name.strip()
        elif isinstance(val, str) and val.strip():
            return val.strip()

    # Flat string keys sometimes present
    for key in ("merchant_name", "store_name", "retailer_name", "brand_name"):
        val = it.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    return ""

def _pick_title(it: Dict[str, Any]) -> str:
    for key in ("name", "title", "item_name", "headline"):
        val = it.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""

def _pick_price(it: Dict[str, Any]) -> str:
    cand = it.get("sale_price") or it.get("current_price") or it.get("price") or it.get("price_text") or ""
    if isinstance(cand, dict):
        for k in ("amount", "dollars", "value"):
            v = cand.get(k)
            if v not in (None, ""):
                return str(v)
        return ""
    return str(cand)

def _pick_url(it: Dict[str, Any]) -> str:
    for key in ("clipping_url", "url", "deep_link_url", "web_url"):
        val = it.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""

def _pick_image(it: Dict[str, Any]) -> str:
    for key in ("grid_image_url", "image_url", "clipping_image_url", "thumbnail_url"):
        val = it.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""

def _pick_dates(it: Dict[str, Any]) -> tuple[str, str]:
    vf = it.get("valid_from") or it.get("start_date") or it.get("starts_at") or ""
    vt = it.get("valid_to") or it.get("expiry_date") or it.get("ends_at") or ""
    return str(vf), str(vt)

def _norm_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize various JSON shapes into a consistent list dict."""
    items = payload.get("items") or payload.get("results") or payload.get("items_internal") or []
    out: List[Dict[str, Any]] = []
    for it in items:
        title = _pick_title(it)
        price = _pick_price(it)
        url = _pick_url(it)
        retailer = _pick_retailer(it)
        if not retailer and url:
            retailer = _infer_store_from_url(url)
        img = _pick_image(it)
        valid_from, valid_to = _pick_dates(it)
        out.append({
            "retailer": retailer,
            "title": title,
            "price": price,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "url": url,
            "image": img,
        })
    return out

def _to_float(price_str: str) -> float:
    try:
        s = str(price_str).replace("$","").replace(",","").strip()
        if not s:
            return 1e9
        return float(s)
    except Exception:
        return 1e9

def _fetch(url: str, params: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return r.status_code, {}
    ctype = (r.headers.get("content-type", "") or "").lower()
    if "application/json" not in ctype:
        return r.status_code, {}
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}

def search_flyers(query: str, postal_code: str, locale: str = "en-ca", limit: int = 30, use_cache: bool = True) -> List[Dict[str, Any]]:
    # Cache key by query+postal+locale
    key = f"q={query.strip().lower()}|pc={postal_code.replace(' ','').upper()}|loc={locale}"
    if use_cache:
        cached = load_json(key)
        if cached:
            items = _norm_items(cached)
            items.sort(key=lambda x: _to_float(x["price"]))
            return items[:limit]

    params = {
        "locale": locale,
        "postal_code": postal_code.replace(" ", ""),
        "q": query,
        "page": 1,
        "per_page": 100,
    }

    # Try primary
    status, data = _fetch(PRIMARY_URL, params)
    if not data and status != 200:
        # Try fallback once
        status, data = _fetch(FALLBACK_URL, params)

    if data and use_cache:
        save_json(key, data)

    items = _norm_items(data) if data else []
    items.sort(key=lambda x: _to_float(x["price"]))
    return items[:limit]
