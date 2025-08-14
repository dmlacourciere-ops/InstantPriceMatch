# tools/barcode.py
# Lightweight UPC/EAN detector. Uses pyzbar if available; otherwise no-ops cleanly.

from typing import List, Tuple, Optional

try:
    from pyzbar.pyzbar import decode as _zbar_decode
    _PYZBAR_OK = True
except Exception:
    _PYZBAR_OK = False

def _normalize_upc(ean: str, symb: str) -> str:
    """
    Normalize common EAN/UPC forms to a UPC-A style string when possible.
    - EAN13 with leading '0' -> UPC-A (drop leading 0)
    - UPCA -> as-is
    - EAN8 / UPCE -> return as-is (some stores accept; we keep it)
    """
    if symb == "EAN13" and ean and ean[0] == "0" and len(ean) == 13:
        return ean[1:]  # 12-digit UPC-A
    return ean

def decode_upc_from_rgb(rgb_img) -> Tuple[Optional[str], List[Tuple[int,int,int,int]]]:
    """
    Args:
        rgb_img: numpy RGB array (H,W,3)
    Returns:
        (upc: Optional[str], boxes: List[x,y,w,h])
    If pyzbar/zbar is not available, returns (None, []).
    """
    if not _PYZBAR_OK or rgb_img is None:
        return None, []

    try:
        # pyzbar expects BGR or grayscale too; RGB works fine
        results = _zbar_decode(rgb_img)
    except Exception:
        return None, []

    boxes: List[Tuple[int,int,int,int]] = []
    best_upc: Optional[str] = None

    for r in results:
        symb = getattr(r, "type", "") or ""
        data = (r.data or b"").decode("utf-8", errors="ignore")
        if not data:
            continue
        x, y, w, h = r.rect.left, r.rect.top, r.rect.width, r.rect.height
        boxes.append((x, y, w, h))

        if symb in ("EAN13", "UPCA", "EAN8", "UPCE"):
            upc = _normalize_upc(data, symb)
            # prefer a 12-digit UPC-A if available
            if best_upc is None or (len(upc) == 12 and best_upc != upc):
                best_upc = upc

    return best_upc, boxes
