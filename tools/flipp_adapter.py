# tools/flipp_adapter.py
import time, json, uuid, requests
from typing import List, Dict

def _locale(country: str) -> str:
    return "en-ca" if str(country).upper() == "CA" else "en-us"

def search_deals(query: str, postal: str, country: str = "CA", limit: int = 10) -> List[Dict]:
    if not query or not postal:
        return []

    base = "https://backflipp.wishabi.com/flipp/items/search"
    params = {
        "locale": _locale(country),
        "postal_code": postal.replace(" ", ""),
        "q": query,
        "sid": str(uuid.uuid4()),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InstantPriceMatch/0.1",
        "Accept": "application/json",
    }

    for _ in range(3):
        try:
            r = requests.get(base, params=params, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                items = data.get("items") or data.get("results") or []
                offers = []
                for it in items:
                    title = it.get("name") or it.get("title") or ""
                    price = it.get("current_price") or it.get("price") or it.get("sale_price")
                    merchant = it.get("merchant") or it.get("store") or {}
                    store = merchant.get("name") if isinstance(merchant, dict) else (merchant or "")
                    flyer_url = it.get("clipping_url") or it.get("share_url") or it.get("url") or ""
                    try:
                        price = float(price)
                    except Exception:
                        continue
                    offers.append({
                        "title": title,
                        "price": price,
                        "store": store,
                        "flyer_url": flyer_url,
                        "source": "Flipp",
                    })
                offers.sort(key=lambda d: d["price"])
                return offers[:limit]
        except requests.RequestException:
            time.sleep(0.6)

    return []
