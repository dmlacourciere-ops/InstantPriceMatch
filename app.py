import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Ensure project root and providers/ are importable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROVIDERS_DIR = os.path.join(BASE_DIR, "providers")
for p in (BASE_DIR, PROVIDERS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.vision_identify import identify_product
try:
    from tools import walmart_adapter as WAL
except Exception:
    WAL = None  # type: ignore

# DEV CAMERA (DroidCam)
try:
    from tools.droidcam import grab_frame as droidcam_grab_frame
except Exception:
    droidcam_grab_frame = None  # type: ignore

def _best_string(*parts: Optional[str]) -> str:
    return " ".join([p.strip() for p in parts if isinstance(p, str) and p.strip()])

def _collect_walmart(upc: Optional[str], name_guess: Optional[str]) -> List[Dict[str, Any]]:
    if WAL is None:
        return []
    try:
        return WAL.lookup_by_upc_or_name(upc=upc, name=name_guess)
    except Exception:
        return []

def _as_price(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return float("inf")

def _summarize_offers(offers: List[Dict[str, Any]]) -> Dict[str, Any]:
    offers_sorted = sorted(offers, key=lambda x: _as_price(x.get("price")))
    cheapest = offers_sorted[0] if offers_sorted else None
    return {"count": len(offers_sorted), "cheapest": cheapest, "offers": offers_sorted}

def run(image: Optional[str], upc: Optional[str], name: Optional[str], country: str,
        droidcam_ip: Optional[str], droidcam_port: int) -> Dict[str, Any]:
    # DEV: if DroidCam IP provided and no image, capture one frame now
    temp_image = None
    if not image and droidcam_ip:
        if droidcam_grab_frame is None:
            raise RuntimeError("DroidCam helper missing. Did you create tools/droidcam.py?")
        temp_image = droidcam_grab_frame(droidcam_ip, droidcam_port)
        image = temp_image

    vision = None
    if image:
        vision = identify_product(image=image, country_hint=country)
        if not upc:
            upc = (vision or {}).get("possible_upc") or None
        if not name:
            name = _best_string(
                (vision or {}).get("brand"),
                (vision or {}).get("name"),
                (vision or {}).get("variant"),
                (vision or {}).get("size_text"),
            ) or None

    walmart_offers = _collect_walmart(upc, name)
    summary = _summarize_offers(walmart_offers)

    out = {
        "input": {"image": image, "upc": upc, "name": name, "country": country, "dev_camera": bool(droidcam_ip)},
        "vision": vision,
        "walmart": summary,
    }

    # (Optional) cleanup temp image
    # if temp_image:
    #     try: os.remove(temp_image)
    #     except Exception: pass

    return out

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instant Price Match — Vision-first lookup (with optional DroidCam for dev)")
    parser.add_argument("--image", default=None, help="Path to an image file (prod flow)")
    parser.add_argument("--upc", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--country", default="CA")
    parser.add_argument("--droidcam-ip", default=None, help="DEV ONLY: phone IP for DroidCam (e.g., 192.168.1.23)")
    parser.add_argument("--droidcam-port", type=int, default=4747, help="DEV ONLY: DroidCam port (default 4747)")
    parser.add_argument("--out", default="last_result.json")
    args = parser.parse_args()

    result = run(
        image=args.image,
        upc=args.upc,
        name=args.name,
        country=args.country,
        droidcam_ip=args.droidcam_ip,
        droidcam_port=args.droidcam_port,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    try:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
