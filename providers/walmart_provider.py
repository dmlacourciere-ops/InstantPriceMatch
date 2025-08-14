import re
import json
import time
import urllib.parse
from typing import List, Dict, Any, Optional

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
}

BASE = "https://www.walmart.ca"
SEARCH_URL = BASE + "/search?q={query}"
DIRECT_IP_URL = BASE + "/en/ip/{upc}"

def _get(url: str, retries: int = 2, timeout: int = 20) -> Optional[requests.Response]:
    last_err = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            last_err = f"HTTP {r.status_code}"
            time.sleep(0.6)
        except Exception as e:
            last_err = str(e)
            time.sleep(0.6)
    print(f"[WALMART] GET failed for {url}: {last_err}")
    return None

def _extract_ldjson(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.text or "{}")
            if isinstance(data, dict):
                out.append(data)
            elif isinstance(data, list):
                out.extend([d for d in data if isinstance(d, dict)])
        except Exception:
            continue
    return out

def _parse_price_from_ld(ld: Dict[str, Any]) -> Optional[float]:
    offers = ld.get("offers")
    if isinstance(offers, dict):
        price = offers.get("price") or offers.get("lowPrice")
        if price is not None:
            try:
                return float(str(price).strip())
            except Exception:
                return None
    return None

def _parse_product_from_response(r: requests.Response, url: str) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(r.text, "lxml")
    ld_list = _extract_ldjson(soup)

    name = None
    price = None
    gtin = None

    for ld in ld_list:
        if ld.get("@type") == "Product":
            name = name or ld.get("name")
            gtin = gtin or ld.get("gtin13") or ld.get("gtin12") or ld.get("sku")
            price = price or _parse_price_from_ld(ld)

    if price is None:
        m = re.search(r'"\$?(\d{1,4}\.\d{2})"', r.text)
        if m:
            try:
                price = float(m.group(1))
            except Exception:
                price = None

    if not (name and price):
        return None

    return {
        "retailer": "Walmart Canada",
        "url": url,
        "product_name": name.strip(),
        "price_cad": float(price),
        "barcode": gtin
    }

def _lookup_direct_ip(upc: str) -> Optional[Dict[str, Any]]:
    url = DIRECT_IP_URL.format(upc=upc)
    r = _get(url)
    if not r:
        return None
    prod = _parse_product_from_response(r, url)
    return prod

def _candidate_links_from_search(soup: BeautifulSoup) -> List[str]:
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/en/ip/") or href.startswith("/en/product/"):
            links.add(href.split("?")[0])
    return [BASE + h for h in links]

def _lookup_via_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    url = SEARCH_URL.format(query=urllib.parse.quote_plus(query))
    r = _get(url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    links = _candidate_links_from_search(soup)
    out: List[Dict[str, Any]] = []
    for link in links[:max_results]:
        r2 = _get(link)
        if not r2:
            continue
        item = _parse_product_from_response(r2, link)
        if item:
            out.append(item)
    return out

def lookup_by_upc_or_name(upc_or_name: str) -> Optional[Dict[str, Any]]:
    q = upc_or_name.strip()
    # 1) If digits, try direct UPC product page FIRST (more reliable than search)
    if q.isdigit():
        direct = _lookup_direct_ip(q)
        if direct:
            return direct
        # fallback: try search page
        found = _lookup_via_search(q, max_results=3)
        return found[0] if found else None

    # 2) For names, try search page; if it yields nothing, caller should try UPCs from another source
    found = _lookup_via_search(q, max_results=5)
    return found[0] if found else None
