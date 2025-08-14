# providers/walmart_playwright.py
# Playwright-powered Walmart Canada lookup (UPC or name)
# Returns: {"name": str, "price": float, "url": str} or None

import re
from typing import Optional, Dict, List

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Page, BrowserContext

BASE = "https://www.walmart.ca"


# ---------- small helpers ----------
def _norm(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def _parse_price_from_text(txt: str | None) -> Optional[float]:
    if not txt:
        return None
    cleaned = txt.replace("\u2009", " ").replace("\xa0", " ").replace(",", "")
    m = re.search(r"(\d{1,4}\.\d{2})", cleaned)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _dismiss_overlays(page: Page) -> None:
    # common consent/bot buttons — ignore failures
    for sel in [
        'button:has-text("Verify")',
        'button:has-text("Continue")',
        'button:has-text("Accept All")',
        'button:has-text("I Agree")',
        'button:has-text("Allow")',
    ]:
        try:
            if page.is_visible(sel, timeout=800):
                page.click(sel)
        except Exception:
            pass


def _looks_like_bot_wall(page: Page) -> bool:
    try:
        body = _norm(page.inner_text("body"))
    except Exception:
        return False
    # Walmart’s shield page often says “Press and hold” / “verify you are human”
    return ("press and hold" in body.lower()) or ("verify you are human" in body.lower())


def _scrape_product_page(page: Page, url: str) -> Optional[Dict]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except PlaywrightTimeoutError:
        return None

    _dismiss_overlays(page)
    page.wait_for_timeout(1500)

    if _looks_like_bot_wall(page):
        # give it one more second to settle; if still bot-wall, bail
        page.wait_for_timeout(1200)
        if _looks_like_bot_wall(page):
            return None

    # ---- NAME ----
    name = None
    for sel in [
        'h1[data-automation="product-title"]',
        'h1[itemprop="name"]',
        'meta[property="og:title"]',
        'h1',
    ]:
        try:
            if sel.startswith("meta"):
                el = page.query_selector(sel)
                if el:
                    content = el.get_attribute("content")
                    name = _norm(content)
            else:
                el = page.query_selector(sel)
                if el:
                    name = _norm(el.inner_text())
            if name:
                break
        except Exception:
            pass

    # ---- PRICE ----
    price_val = None
    for sel in [
        '[data-automation="buybox-price"]',
        'section[aria-label*="Buy box"]',
        'span[aria-label*="$"]',
        'div[aria-label*="$"]',
        'span:has-text("$")',
        'div:has-text("$")',
        'meta[property="product:price:amount"]',
        'meta[property="og:price:amount"]',
    ]:
        try:
            if sel.startswith("meta"):
                el = page.query_selector(sel)
                if el:
                    content = el.get_attribute("content")
                    price_val = _parse_price_from_text(content)
            else:
                el = page.query_selector(sel)
                if el:
                    price_val = _parse_price_from_text(el.inner_text())
            if price_val is not None:
                break
        except Exception:
            pass

    # last-resort: search whole body
    if price_val is None:
        try:
            price_val = _parse_price_from_text(page.inner_text("body"))
        except Exception:
            pass

    if not (name and price_val):
        return None

    return {"name": name, "price": float(price_val), "url": url}


def _first_product_from_search(page: Page, query: str) -> Optional[Dict]:
    search_url = f"{BASE}/search?q={query}"
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
    except PlaywrightTimeoutError:
        return None

    _dismiss_overlays(page)
    page.wait_for_timeout(1500)

    if _looks_like_bot_wall(page):
        page.wait_for_timeout(1200)
        if _looks_like_bot_wall(page):
            return None

    # product tile link
    anchors: List = []
    try:
        anchors = page.query_selector_all(
            'a[href^="/en/ip/"], a[href^="/en/product/"], a[data-automation="product-title"]'
        )
    except Exception:
        pass

    if not anchors:
        return None

    href = anchors[0].get_attribute("href")
    if not href:
        return None

    prod_url = BASE + href.split("?")[0] if href.startswith("/") else href
    return _scrape_product_page(page, prod_url)


def _new_context(pw) -> BrowserContext:
    browser = pw.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--start-maximized",
        ],
    )
    context = browser.new_context(
        locale="en-CA",
        timezone_id="America/Toronto",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 850},
    )
    # Reduce automation fingerprints
    context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """
    )
    return context


# ---------- public entry ----------
def walmart_lookup_playwright(upc_or_name: str) -> Optional[Dict]:
    """
    If digits: try /en/ip/{UPC} first, then search.
    If name: go straight to search and scrape first product.
    Returns dict {"name","price","url"} or None.
    """
    q = _norm(upc_or_name)
    if not q:
        return None

    with sync_playwright() as pw:
        context = _new_context(pw)
        page = context.new_page()
        try:
            if q.isdigit():
                direct = f"{BASE}/en/ip/{q}"
                item = _scrape_product_page(page, direct)
                if item:
                    return item
                return _first_product_from_search(page, q)
            else:
                return _first_product_from_search(page, q)
        finally:
            context.close()
def lookup_by_upc_or_name(upc=None, name=None):
    """
    Compatibility wrapper for the app. Delegates to walmart_lookup_playwright
    and tries a few common call signatures. Returns a list of dicts.
    """
    try:
        f = walmart_lookup_playwright  # defined above in this file
    except Exception:
        return []

    attempts = []

    # Best-guess signatures. We try broadly but ignore TypeError mismatches.
    if upc is not None or name is not None:
        attempts.append(lambda: f(upc=upc, name=name))
    if name:
        attempts.append(lambda: f(name=name))
        attempts.append(lambda: f(query=name))
        attempts.append(lambda: f(search=name))
        attempts.append(lambda: f(name=name, upc=None))
    if upc:
        attempts.append(lambda: f(upc=upc))
        attempts.append(lambda: f(query=upc))
        attempts.append(lambda: f(search=upc))
        attempts.append(lambda: f(name=None, upc=upc))

    # Last resort: pass a single string when only one is provided
    if name and not upc:
        attempts.append(lambda: f(name))
    if upc and not name:
        attempts.append(lambda: f(upc))

    for call in attempts:
        try:
            res = call()
            if res:
                return res
        except TypeError:
            # Signature mismatch, try the next one
            continue
        except Exception:
            # Network/parse error etc—try next
            continue
    return []
# ---- simple public wrapper: UPC/EAN -> list[offer] ----
# Offer shape: {"store": "Walmart", "price": float, "currency": "CAD"/"USD", "url": str, "title": str}
def get_offers_by_upc(upc: str, country: str = "CA"):
    """
    Minimal wrapper around walmart_lookup_playwright that normalizes the output
    into a list of offers our app expects. Currently optimized for Walmart Canada.
    """
    if not upc:
        return []

    # Normalize UPC as a string; callers sometimes pass short codes without leading zeros.
    upc_str = str(upc).strip()

    try:
        # Reuse your existing page-scraper (Canada-focused)
        item = walmart_lookup_playwright(upc_str)
    except Exception:
        item = None

    if not item:
        return []

    # item is like {"name": str, "price": float, "url": str}
    try:
        price = float(item.get("price"))
    except Exception:
        return []

    offer = {
        "store": "Walmart",
        "price": price,
        "currency": "CAD" if str(country).upper() == "CA" else "USD",
        "url": item.get("url") or "",
        "title": item.get("name") or f"UPC {upc_str}",
    }
    return [offer]
