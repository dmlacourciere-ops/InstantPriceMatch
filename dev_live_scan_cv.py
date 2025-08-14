# dev_live_scan_cv.py — patched safe edition
# Hybrid live scanner (DroidCam -> OpenCV) with safer threading,
# duplicate suppression, robust logging, and proof generation.
#
# Drop-in replacement for your existing dev_live_scan_cv.py.
# Tested with Python 3.12 + OpenCV 4.12 on Windows.
#
# Launch example:
#   .\.venv312\Scripts\python.exe -X faulthandler -u .\dev_live_scan_cv.py --ip 10.0.0.187 --port 4747 --country CA --store Walmart

from __future__ import annotations

import os, sys, json, time, tempfile, threading, webbrowser, traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# ====== paths & logging ======
BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
CAP_DIR  = BASE_DIR / "captures"
CAP_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = CAP_DIR / "run.log"

def dprint(*a: Any) -> None:
    """Print to console and append to run.log, never crash."""
    msg = "[DEV] " + " ".join(str(x) for x in a)
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

dprint("=== dev_live_scan_cv.py (patched) starting ===")

# Make sure our folders are importable
for p in (BASE_DIR, BASE_DIR / "tools", BASE_DIR / "providers"):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

# ====== optional/soft imports ======
try:
    from tools.droidcam import open_capture, read_frame_rgb
except Exception as e:
    dprint("FATAL import error (droidcam):", e)
    raise

try:
    from tools.barcode import decode_upc_from_rgb
except Exception as e:
    dprint("FATAL import error (barcode):", e)
    raise

try:
    from tools.vision_identify import identify_product  # vision label reader
except Exception as e:
    dprint("FATAL import error (vision_identify):", e)
    raise

# proof composer (optional)
make_proof_png = None
try:
    from tools.proof_png import make_proof_png as _make_proof_png
    make_proof_png = _make_proof_png
except Exception as e:
    dprint("INFO: proof composer unavailable, proof images disabled:", e)

# price providers (optional)
WAL = None
try:
    from providers.walmart_adapter import walmart_adapter as _WAL
    WAL = _WAL
except Exception as e:
    dprint("INFO: walmart adapter unavailable:", e)

FLP = None
try:
    from providers.flipp_adapter import flipp_adapter as _FLP
    FLP = _FLP
except Exception as e:
    dprint("INFO: flipp adapter unavailable:", e)

# ====== knobs ======
SCAN_EVERY_SECONDS = 1.2   # throttle vision calls (UI is 30/60 fps)
HITS_NEEDED        = 2     # consecutive matches to treat as a lock
LIST_WINDOW_NAME   = "Found Items"
WINDOW_NAME        = "InstantPriceMatch ◀ DEV (Esc=Quit,  r=Rotate 90°)"
FONT               = cv2.FONT_HERSHEY_SIMPLEX

# capture flood protection
COOLDOWN_SEC       = 8     # don't create another capture/proof for same key within this many seconds
MIN_BRIGHTNESS     = 12.0  # skip very dark/black frames

# HTML outputs
RESULTS_HTML = CAP_DIR / "results.html"
JSON_LOG     = CAP_DIR / "found_items.json"
CSV_LOG      = CAP_DIR / "found_items.csv"

# ====== runtime state ======
latest_upc: Optional[str] = None
latest_vision: Optional[Dict[str, Any]] = None
upc_hit_count = 0
results_page_opened = False
price_lookup_inflight = False

# history
history_by_key: Dict[str, Dict[str, Any]] = {}
history_order: List[str] = []      # newest at front
MAX_LIST_ITEMS = 12

# duplicate suppression
last_commit_ts: Dict[str, float] = {}  # key -> last capture timestamp

# rotation
ROTATE_DEG = 0

# ====== helpers ======
def _best_string(*parts: Optional[str]) -> str:
    s = " ".join([p.strip() for p in parts if isinstance(p, str) and p.strip()])
    return s if s else "(recognizing…)"

def _key_for(upc: Optional[str], vision: Optional[Dict[str, Any]]) -> str:
    if upc: return f"UPC:{upc}"
    if vision:
        brand = (vision.get("brand") or "").strip().lower()
        name = (vision.get("name") or "").strip().lower()
        variant = (vision.get("variant") or "").strip().lower()
        size = (vision.get("size_text") or "").strip().lower()
        return f"VIS:{brand}|{name}|{variant}|{size}"
    return "VIS:unknown"

def _encode_to_jpeg_bytes(rgb: np.ndarray) -> bytes:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()

def _render_list_window() -> None:
    canvas = np.ones((340, 600, 3), dtype=np.uint8) * 245
    y = 24
    cv2.putText(canvas, "Found items — cheapest first when available", (10, y), FONT, 0.55, (20,20,20), 1, cv2.LINE_AA)
    y += 16
    for idx, key in enumerate(history_order[:MAX_LIST_ITEMS], start=1):
        e = history_by_key.get(key, {})
        title = _best_string(e.get("brand"), e.get("name"), e.get("variant"))
        size = e.get("size_text") or "—"
        best = e.get("best_price") or "???"
        line = f"{idx}. | {title[:40]:<40} | Size: {size[:10]:<10} | Best: {str(best)[:9]:<9}"
        y += 22
        cv2.putText(canvas, line, (10, y), FONT, 0.5, (10,10,10), 1, cv2.LINE_AA)
    cv2.imshow(LIST_WINDOW_NAME, canvas)

def _safe_uri(p: Path) -> Optional[str]:
    try:
        return p.resolve().as_uri()
    except Exception:
        return None

def _write_results_html(rows: List[Dict[str, Any]]) -> None:
    html = ['<!doctype html><html><meta charset="utf-8">',
            '<meta http-equiv="refresh" content="2">',
            '<title>Instant Price Match – Results</title>',
            '<style>body{font-family:Arial,Helvetica,sans-serif;margin:18px;background:#f7f7f7;color:#222}',
            '.item{background:#fff;border-radius:10px;padding:12px;margin:10px 0;box-shadow:0 1px 6px rgba(0,0,0,.06)}',
            '.thumb{width:100px;height:100px;object-fit:cover;border-radius:8px;border:1px solid #eee;margin-right:16px}',
            '.meta{opacity:.7;font-size:14px} .title{font-size:18px;font-weight:600} a{color:#0866c2;text-decoration:none}',
            'a:hover{text-decoration:underline}</style><body><h2>Found Items</h2>']
    for r in rows:
        title = _best_string(r.get("brand"), r.get("name"), r.get("variant"))
        size = r.get("size_text") or "—"
        best = r.get("best_price") or "—"
        url = r.get("best_url") or ""
        proof = r.get("proof_path") or ""
        img = r.get("capture_path") or ""
        img_src = _safe_uri(Path(img)) or ""
        url_html = f'<a href="{url}" target="_blank">(url)</a>' if url else "<em>No URL yet</em>"
        proof_html = f'<a href="{_safe_uri(Path(proof))}">(proof)</a>' if proof and _safe_uri(Path(proof)) else "(proof)"
        block = f'''<div class="item">
            <div style="display:flex;align-items:center">
              <img class="thumb" src="{img_src}" alt="thumb">
              <div>
                <div class="title">{title}</div>
                <div class="meta">Size: {size} &nbsp; | &nbsp; Best: {best} &nbsp; {url_html} &nbsp; {proof_html}</div>
              </div>
            </div>
          </div>'''
        html.append(block)
    html.append("</body></html>")
    try:
        RESULTS_HTML.write_text("\n".join(html), encoding="utf-8")
    except Exception as e:
        dprint("write results html error:", e)

def _write_logs_and_results_page() -> None:
    rows: List[Dict[str, Any]] = []
    for key in history_order:
        rows.append(history_by_key.get(key, {}))
    # JSON
    try:
        JSON_LOG.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        dprint("write JSON error:", e)
    # CSV (minimal)
    try:
        import csv
        fields = ["ts_iso","brand","name","variant","size_text","best_price","best_url","capture_path","proof_path"]
        with CSV_LOG.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({
                    "ts_iso": r.get("ts_iso",""),
                    "brand": r.get("brand",""),
                    "name": r.get("name",""),
                    "variant": r.get("variant",""),
                    "size_text": r.get("size_text",""),
                    "best_price": r.get("best_price",""),
                    "best_url": r.get("best_url",""),
                    "capture_path": r.get("capture_path",""),
                    "proof_path": r.get("proof_path","")
                })
    except Exception as e:
        dprint("write CSV error:", e)
    _write_results_html(rows)

def _ensure_entry(key: str, v: Dict[str, Any], capture_path: Path) -> Dict[str, Any]:
    # Merge or create
    now_iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    entry = history_by_key.get(key, {})
    entry.update({
        "ts_iso": now_iso,
        "brand": v.get("brand"),
        "name": v.get("name"),
        "variant": v.get("variant"),
        "size_text": v.get("size_text"),
        "possible_upc": v.get("possible_upc") or "",
        "capture_path": str(capture_path)
    })
    history_by_key[key] = entry
    if key in history_order:
        history_order.remove(key)
    history_order.insert(0, key)
    del history_order[MAX_LIST_ITEMS:]  # trim
    return entry

def _collect_offers(upc: Optional[str], name_guess: Optional[str]) -> List[Dict[str, Any]]:
    offers: List[Dict[str, Any]] = []
    # Walmart
    if WAL:
        try:
            offers.extend([{"store":"walmart", **o} for o in WAL.lookup_by_upc_or_name(upc=upc, name=name_guess) or []])
        except Exception as e:
            dprint("Walmart lookup error:", e)
    # Flipp
    if FLP:
        try:
            offers.extend([{"store":"flipp", **o} for o in FLP.lookup(upc=upc, name=name_guess) or []])
        except Exception as e:
            dprint("Flipp lookup error:", e)
    # Normalize price to float for sorting if present
    def _price(x):
        try:
            return float(x.get("price"))
        except Exception:
            return float("inf")
    offers.sort(key=_price)
    return offers

def _download_image(url: str) -> Optional[Path]:
    if not url: return None
    try:
        import requests
        r = requests.get(url, timeout=6)
        if r.status_code != 200 or not r.content:
            return None
        out = CAP_DIR / f"proof_src_{int(time.time())}.jpg"
        out.write_bytes(r.content)
        return out
    except Exception:
        return None

def _price_lookup_thread(key: str, v: Dict[str, Any]) -> None:
    global price_lookup_inflight
    try:
        upc = v.get("possible_upc") or None
        name_guess = _best_string(v.get("brand"), v.get("name"), v.get("variant"), v.get("size_text"))
        offers = _collect_offers(upc, name_guess)
        entry = history_by_key.get(key, {})
        if offers:
            best = offers[0]
            entry["best_store"] = (best.get("store") or "").title()
            entry["best_price"] = str(best.get("price") or "")
            entry["best_url"]   = str(best.get("url") or "")

            # optional flyer/thumbnail for proof
            proof_src = _download_image(best.get("image") or "")

            # compose a proof (optional)
            if make_proof_png:
                try:
                    cap_path = Path(entry.get("capture_path") or "")
                    out_path = CAP_DIR / f"proof_{int(time.time())}.png"
                    entry["proof_path"] = str(out_path)
                    make_proof_png(
                        out_path=out_path,                  # patched: explicit keyword
                        camera_path=cap_path,
                        flyer_path=str(proof_src) if proof_src else "",
                        title=_best_string(entry.get("brand"), entry.get("name"), entry.get("variant")),
                        store=entry.get("best_store") or "",
                        price_text=entry.get("best_price") or "-",
                        url=entry.get("best_url") or ""
                    )
                    dprint("Proof composed:", entry["proof_path"])
                except Exception as e:
                    dprint("Proof compose error:", e)

            # open best URL once (safe)
            if entry.get("best_url") and not entry.get("opened_url"):
                try:
                    webbrowser.open_new_tab(entry["best_url"])
                    entry["opened_url"] = "yes"
                    dprint("Opened URL:", entry["best_url"])
                except Exception as e:
                    dprint("Open URL error:", e)
        else:
            dprint("--- No offers found yet (Walmart+Flipp) ---")
    except Exception as e:
        dprint("price lookup thread error:", e, traceback.format_exc())
    finally:
        price_lookup_inflight = False
        _write_logs_and_results_page()

def _ensure_results_page_opened_once() -> None:
    global results_page_opened
    if results_page_opened and RESULTS_HTML.exists():
        return
    try:
        uri = _safe_uri(RESULTS_HTML)
        if uri:
            webbrowser.open_new_tab(uri)
        results_page_opened = True
        dprint("Opened results page:", RESULTS_HTML)
    except Exception as e:
        dprint("Open results page error:", e)

def _rotate_frame(rgb: np.ndarray, degrees: int) -> np.ndarray:
    d = degrees % 360
    if d == 90:  return cv2.rotate(rgb, cv2.ROTATE_90_CLOCKWISE)
    if d == 180: return cv2.rotate(rgb, cv2.ROTATE_180)
    if d == 270: return cv2.rotate(rgb, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return rgb

# ====== main worker ======
def _vision_worker(country: str) -> None:
    global latest_vision, price_lookup_inflight
    dprint("Vision worker started. Country:", country)
    last_scan = 0.0

    while True:
        # frame is supplied via globals (set in main loop), we only drive scans here
        try:
            now = time.time()
            if now - last_scan < SCAN_EVERY_SECONDS:
                time.sleep(0.02)
                continue
            last_scan = now

            frame = _FRAME_HUB.get_latest()
            if frame is None:
                time.sleep(0.02)
                continue

            # brightness gate
            if frame.mean() < MIN_BRIGHTNESS:
                continue

            # Save to temp and call vision_identify
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp.write(_encode_to_jpeg_bytes(frame))
            tmp.close()
            img_path = tmp.name
            try:
                v = identify_product(image=img_path, country_hint=country, debug=False) or {}
            except Exception as e:
                dprint("identify_product error:", e)
                v = {}
            finally:
                try:
                    os.unlink(img_path)
                except Exception:
                    pass

            if not v:
                continue

            latest_vision = v

            # Keying / cooldown
            upc = v.get("possible_upc") or None
            key = _key_for(upc, v)
            now_ts = time.time()
            last_ts = last_commit_ts.get(key, 0.0)
            if now_ts - last_ts < COOLDOWN_SEC:
                # Still update HUD and list window without writing duplicates
                _render_list_window()
                continue
            last_commit_ts[key] = now_ts

            # commit capture
            out_jpg = CAP_DIR / f"capture_{int(now_ts)}.jpg"
            out_jpg.write_bytes(_encode_to_jpeg_bytes(frame))
            entry = _ensure_entry(key, v, out_jpg)
            _write_logs_and_results_page()
            _ensure_results_page_opened_once()

            # Spawn price lookup if not already
            if not price_lookup_inflight:
                price_lookup_inflight = True
                threading.Thread(target=_price_lookup_thread, args=(key, v), daemon=True).start()
        except Exception as e:
            dprint("Vision worker loop error:", e, traceback.format_exc())
            time.sleep(0.2)

# ====== frame hub between threads ======
class _FrameHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Optional[np.ndarray] = None

    def set(self, rgb: Optional[np.ndarray]) -> None:
        with self._lock:
            self._latest = None if rgb is None else rgb.copy()

    def get_latest(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._latest is None:
                return None
            return self._latest.copy()

_FRAME_HUB = _FrameHub()

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Instant Price Match – DEV hybrid scanner (DroidCam + CV)")
    parser.add_argument("--ip", required=True)
    parser.add_argument("--port", type=int, default=4747)
    parser.add_argument("--country", default="CA")
    parser.add_argument("--store", default="Walmart")
    args = parser.parse_args()

    # Env diagnostics
    dprint("Python:", sys.version)
    dprint("cv2.__version__:", getattr(cv2, "__version__", "?"))
    key = os.getenv("OPENAI_API_KEY") or ""
    dprint("OPENAI_API_KEY present:", bool(key), "len:", len(key))

    # DroidCam
    url = f"http://{args.ip}:{args.port}/video"
    dprint("Opening DroidCam stream:", url)

    cap = None
    try:
        cap = open_capture(args.ip, args.port)
    except Exception as e:
        dprint("FATAL: cannot open DroidCam:", e)
        raise

    # UI windows
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 960, 540)
    cv2.namedWindow(LIST_WINDOW_NAME, cv2.WINDOW_AUTOSIZE)

    # Vision worker
    threading.Thread(target=_vision_worker, args=(args.country,), daemon=True).start()

    global latest_upc, upc_hit_count, ROTATE_DEG

    try:
        while True:
            ok, rgb = read_frame_rgb(cap)
            if not ok or rgb is None:
                # show missing frame notice and keep loop alive
                canvas = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(canvas, "No frames from DroidCam...", (40, 180), FONT, 0.7, (255,255,255), 2, cv2.LINE_AA)
                cv2.imshow(WINDOW_NAME, canvas)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
                time.sleep(0.05)
                continue

            # rotate
            rgb = _rotate_frame(rgb, ROTATE_DEG)

            # barcode pass
            upc, boxes = None, []
            try:
                upc, boxes = decode_upc_from_rgb(rgb)  # returns (upc, [(x,y,w,h),...]) or (None, [])
            except Exception as e:
                dprint("barcode decode error:", e)

            # track hits
            if upc:
                upc_hit_count = upc_hit_count + 1 if upc == latest_upc else 1
                latest_upc = upc
            else:
                upc_hit_count = 0

            # HUD draw
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            for (x,y,w,h) in boxes or []:
                cv2.rectangle(bgr, (x,y), (x+w, y+h), (0,255,0), 2, cv2.LINE_AA)

            if upc and upc_hit_count >= HITS_NEEDED:
                sub = "LOCKED"
                info_title = _best_string("UPC:", upc)
                # synthesize a minimal vision dict so list view has something immediately
                v0 = {
                    "brand": "",
                    "name": "",
                    "variant": "",
                    "size_text": "",
                    "possible_upc": upc
                }
                key = _key_for(upc, v0)
                now_ts = time.time()
                if now_ts - last_commit_ts.get(key, 0.0) >= COOLDOWN_SEC and bgr.mean() >= MIN_BRIGHTNESS:
                    last_commit_ts[key] = now_ts
                    out_jpg = CAP_DIR / f"capture_{int(now_ts)}.jpg"
                    try:
                        out_jpg.write_bytes(_encode_to_jpeg_bytes(rgb))
                        _ensure_entry(key, v0, out_jpg)
                        _write_logs_and_results_page()
                        _ensure_results_page_opened_once()
                        # price lookup thread can use UPC right away
                        global price_lookup_inflight
                        if not price_lookup_inflight:
                            price_lookup_inflight = True
                            threading.Thread(target=_price_lookup_thread, args=(key, v0), daemon=True).start()
                    except Exception as e:
                        dprint("capture write error:", e)
            else:
                sub = "SCANNING"
                info_title = "Recognizing…    (hold front label steady)"

            # Footer
            cv2.putText(bgr, sub, (20, bgr.shape[0]-18), FONT, 0.8, (12,180,255) if sub=="SCANNING" else (0,255,0), 2, cv2.LINE_AA)
            cv2.putText(bgr, "Esc: Quit   |   r: Rotate 90°", (20, bgr.shape[0]-4), FONT, 0.55, (210,210,210), 1, cv2.LINE_AA)

            # Title overlay
            cv2.putText(bgr, info_title, (12, 26), FONT, 0.8, (255,255,255), 2, cv2.LINE_AA)

            cv2.imshow(WINDOW_NAME, bgr)
            _render_list_window()

            keypress = cv2.waitKey(1) & 0xFF
            if keypress == 27:  # Esc
                break
            if keypress in (ord('r'), ord('R')):
                ROTATE_DEG = (ROTATE_DEG + 90) % 360
    except Exception as e:
        dprint("FATAL:", e, traceback.format_exc())
        raise
    finally:
        dprint("Shutting down…")
        try:
            _FRAME_HUB.set(None)
        except Exception:
            pass
        try:
            cap.release()
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

if __name__ == "__main__":
    main()
