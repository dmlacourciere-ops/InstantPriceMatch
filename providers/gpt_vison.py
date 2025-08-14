# providers/gpt_vision.py
from __future__ import annotations
import base64, json, mimetypes, os
from pathlib import Path
from typing import Optional, Dict

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL_NAME = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")  # override if you want

def _read_image_as_data_url(p: Path) -> str:
    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    data = p.read_bytes()
    b64  = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"

def identify_product(image_path: str, timeout: float = 30.0) -> Optional[Dict]:
    """
    Returns: { 'product_name': str, 'brand': str|None, 'size': str|None, 'upc': str|None }
    or None if not confident.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None  # no key → silently let caller fallback

    p = Path(image_path)
    if not p.exists():
        return None

    img_data_url = _read_image_as_data_url(p)
    prompt = (
        "You are labeling a grocery product for price matching. "
        "Return a compact JSON object with keys: product_name, brand, size, upc (if visible). "
        "Be concise and avoid marketing fluff."
    )

    import requests
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": MODEL_NAME,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type":"text", "text": prompt},
                    {"type":"image_url", "image_url": {"url": img_data_url}},
                ],
            }
        ]
    }
    try:
        r = requests.post(OPENAI_URL, headers=headers, json=body, timeout=timeout)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        # Try to parse JSON if present, else return as product_name
        try:
            data = json.loads(text)
            name = (data.get("product_name") or "").strip()
            if not name:
                return None
            return {
                "product_name": name,
                "brand": (data.get("brand") or "").strip() or None,
                "size": (data.get("size") or "").strip() or None,
                "upc":  (data.get("upc") or "").strip() or None,
            }
        except Exception:
            # Model replied with plain text → use as name
            if not text:
                return None
            return {"product_name": text, "brand": None, "size": None, "upc": None}
    except Exception:
        return None
