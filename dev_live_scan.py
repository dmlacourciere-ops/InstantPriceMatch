# dev_live_scan_cv.py
# Hybrid live scanner with debug prints & run log so we can see where it stops.
# (Barcode + Vision, HTML results, Proof PNG) — with extra diagnostics enabled.

import os, sys, csv, json, time, tempfile, threading, webbrowser, traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple

import cv2
import numpy as np

DEBUG = True
def dprint(*a):
    msg = "[DEV] " + " ".join(str(x) for x in a)
    print(msg, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAP_DIR   = Path(BASE_DIR) / "captures"
LOG_PATH  = CAP_DIR / "run.log"
for p in (BASE_DIR, os.path.join(BASE_DIR, "tools"), os.path.join(BASE_DIR, "providers")):
    if p not in sys.path:
        sys.path.insert(0, p)
CAP_DIR.mkdir(parents=True, exist_ok=True)

# --- imports of our modules
dprint("Importing app modules...")
from tools.droidcam import open_capture, read_frame_rgb
from tools.barcode import decode_upc_from_rgb
from tools.vision_identify import identify_product
from tools.proof_png import make_proof_png
try:
    from tools import walmart_adapter as WAL
except Exception:
    WAL = None  # type: ignore
try:
    from tools import flipp_adapter as FLP
except Exception:
    FLP = None  # type: ignore

# ----- Config -----
SCAN_EVERY_SECONDS = 1.2
HITS_NEEDED = 2
BEEP_ON_LOCK = True
WINDOW_NAME = "InstantPriceMatch — DEV (Esc=Quit, r=Rotate 90°)"
LIST_WINDOW = "Found Items"
PROOF_WINDOW = "Proof Image"
FONT = cv2.FONT_HERSHEY_SIMPLEX
ROTATE_DEG = 0
MAX_LIST_ITEMS = 12

# ----- Shared state -----
last_frame_rgb: Optional[np.ndarray] = None
latest_vision: Optional[Dict[str, Any]] = None
last_vision_key: str = ""
vision_hit_count: int = 0
locked_keys: set[str] = set()  # "UPC:<code>" or "VIS:<key>"
price_lookup_inflight: bool = False

# For UPC fast lock
latest_upc: Optional[str] = None
last_upc: str = ""
upc_hit_count: int = 0

# History (keyed) + display order
history_by_key: Dict[str, Dict[str, Any]] = {}
history_order: List[str] = []

JSON_LOG = CAP_DIR / "found_items.json"
CSV_LOG  = CAP_DIR / "found_items.csv"
RESULTS_HTML = CAP_DIR / "results.html"
results_page_opened = False

lock_obj = threading.Lock()
stop_flag = False

def _best_string(*parts: Optional[str]) -> str:
    return " ".join([p.strip() for p in parts if isinstance(p, str) and p.strip()])

def _prod_key(v: Dict[str, Any]) -> str:
    s = _best_string(v.get("brand"), v.get("name"), v.get("variant"), v.get("size_text"))
    return " ".join(s.lower().split())

def _encode_to_jpeg_bytes(rgb: np.ndarray) -> bytes:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()

def _beep():
    if not BEEP_ON_LOCK:
        return
    try:
        import winsound
        winsound.Beep(1000, 120)
    except Exception:
        pass

def _draw_bottom_check(frame_bgr: np.ndarray, locked: bool):
    h, w = frame_bgr.shape[:2]
    x0, y0 = 30, h - 30
    color = (0, 180, 60) if locked else (40, 40, 255)
    thickness = 4 if locked else 2
    cv2.line(frame_bgr, (x0, y0), (x0 + 15, y0 + 15), color, thickness, cv2.LINE_AA)
    cv2.line(frame_bgr, (x0 + 15, y0 + 15), (x0 + 45, y0 - 20), color, thickness, cv2.LINE_AA)
    label = "LOCKED" if locked else "SCANNING"
    cv2.putText(frame_bgr, label, (x0 + 60, y0), FONT, 0.6, color, 2, cv2.LINE_AA)

def _draw_hud(frame_bgr, info: str, sub: str = ""):
    overlay = frame_bgr.copy()
    cv2.rectangle(overlay, (0, 0), (frame_bgr.shape[1], 60), (0, 0, 0), -1)
    frame_bgr[:] = cv2.addWeighted(overlay, 0.35, frame_bgr, 0.65, 0)
    cv2.putText(frame_bgr, info, (12, 26), FONT, 0.8, (255,255,255), 2, cv2.LINE_AA)
    if sub:
        cv2.putText(frame_bgr, sub, (12, 50), FONT, 0.55, (220,220,220), 1, cv2.LINE_AA)

def _rows_for_logs() -> List[Dict[str, Any]]:
    return [history_by_key[k] for k in history_order]

def _write_results_html(rows: List[Dict[str, Any]]):
    def _safe_uri(p: Optional[str]) -> str:
        if not p: return ""
        try: return Path(p).resolve().as_uri()
        except Exception: return ""
    html = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta http-equiv='refresh' content='2'>",
        "<title>Instant Price Match — Results</title>",
        "<style>body{font-family:Arial,Helvetica,sans-serif;margin:18px;background:#f7f7f7;color:#222}",
        ".item{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px;margin:10px 0;display:flex;gap:14px;align-items:center}",
        ".thumb{width:100px;height:100px;object-fit:cover;border-radius:8px;border:1px solid #ddd}",
        ".meta{flex:1}.title{font-weight:700;font-size:15px;margin-bottom:4px}",
        ".row{font-size:14px;color:#444}.link a{color:#0a66c2;text-decoration:none}.link a:hover{text-decoration:underline}",
        "</style></head><body><h2>Found Items</h2>"
    ]
    for r in rows:
        title = _best_string(r.get("brand"), r.get("name"), r.get("variant")) or "(recognizing...)"
        size  = r.get("size_text") or "—"
        best_price = r.get("best_price") or "—"
        best_store = (r.get("best_store") or "").title()
        url = r.get("best_url") or ""
        proof = r.get("proof_path") or r.get("capture_path") or ""
        img_src_uri = _safe_uri(proof)
        url_html = f"<a href='{url}' target='_blank'>{url}</a>" if url else "<em>No URL yet</em>"
        store_html = f"{best_price} @ {best_store}" if best_store else best_price
        html += [
            "<div class='item'>",
            f"<img class='thumb' src='{img_src_uri}' alt='proof'><div class='meta'>",
            f"<div class='title'>{title}</div>",
            f"<div class='row'>Size: {size} &nbsp; | &nbsp; Best: {store_html}</div>",
            f"<div class='link'>{url_html}</div>",
            "</div></div>"
        ]
    html += ["</body></html>"]
    RESULTS_HTML.write_text("\n".join(html), encoding="utf-8")

def _write_logs_and_results_page():
    rows = _rows_for_logs()
    JSON_LOG.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["ts_iso","brand","name","variant","size_text","possible_upc","notes",
              "best_store","best_price","best_url","proof_path","capture_path","opened_url"]
    with CSV_LOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            r2 = {k: r.get(k,"") for k in fields}
            w.writerow(r2)
    _write_results_html(rows)

def _ensure_entry(key: str, v: Dict[str, Any], capture_path: Path):
    now_iso = datetime.now().isoformat(timespec="seconds")
    entry = history_by_key.get(key) or {}
    entry.update({
        "ts_iso": now_iso,
        "brand": v.get("brand",""),
        "name": v.get("name",""),
        "variant": v.get("variant",""),
        "size_text": v.get("size_text",""),
        "possible_upc": v.get("possible_upc",""),
        "notes": v.get("notes",""),
        "capture_path": str(capture_path),
        "best_store": entry.get("best_store",""),
        "best_price": entry.get("best_price",""),
        "best_url": entry.get("best_url",""),
        "proof_path": entry.get("proof_path",""),
        "opened_url": entry.get("opened_url",""),
    })
    history_by_key[key] = entry
    if key in history_order: history_order.remove(key)
    history_order.insert(0, key)
    del history_order[MAX_LIST_ITEMS:]

def _render_list_window():
    w, h = 620, 34 + 34*MAX_LIST_ITEMS
    canvas = np.ones((h, w, 3), dtype=np.uint8) * 245
    cv2.rectangle(canvas, (0,0), (w-1, h-1), (210,210,210), 1)
    cv2.putText(canvas, "Found Items — cheapest first when available", (10, 24), FONT, 0.6, (30,30,30), 2, cv2.LINE_AA)
    y = 54
    line_gap = 34
    idx = 1
    for key in history_order[:MAX_LIST_ITEMS]:
        e = history_by_key.get(key, {})
        title = _best_string(e.get("brand"), e.get("name"), e.get("variant"))
        size  = e.get("size_text","") or "—"
        price = e.get("best_price","") or "—"
        store = (e.get("best_store","") or "").title()
        row = f"{idx:2d}. {title}  |  {size}  |  Best: {price} {('@ '+store) if store else ''}"
        cv2.putText(canvas, row, (12, y), FONT, 0.55, (20,20,20), 1, cv2.LINE_AA)
        y += line_gap; idx += 1
    cv2.imshow(LIST_WINDOW, canvas)

def _download_image(url: str) -> Optional[Path]:
    if not url: return None
    import requests
    try:
        r = requests.get(url, timeout=6)
        if not r.ok or not r.content: return None
        path = CAP_DIR / f"proof_src_{int(time.time())}.jpg"
        path.write_bytes(r.content)
        return path
    except Exception:
        return None

def _collect_offers(upc: Optional[str], name_guess: Optional[str]) -> List[Dict[str, Any]]:
    offers: List[Dict[str, Any]] = []
    if WAL is not None:
        try:
            wl = WAL.lookup_by_upc_or_name(upc=upc, name=name_guess) or []
            offers.extend([{**o, "store": o.get("store","walmart")} for o in wl])
        except Exception as e:
            dprint("Walmart lookup error:", e)
    if FLP is not None:
        try:
            fl = FLP.lookup(upc=upc, name=name_guess) or []
            offers.extend(fl)
        except Exception as e:
            dprint("Flipp lookup error:", e)
    def _pf(v):
        try: return float(v)
        except: return 1e12
    offers = sorted(offers, key=lambda x: _pf(x.get("price")))
    return offers

def _price_lookup_thread(key: str, v: Dict[str, Any]):
    dprint("Lookup thread started for", key)
    upc = v.get("possible_upc") or None
    name_guess = _best_string(v.get("brand"), v.get("name"), v.get("variant"), v.get("size_text")) or None
    offers = _collect_offers(upc, name_guess)
    best = offers[0] if offers else None

    if offers:
        print("\n--- Price results ---", flush=True)
        for o in offers[:10]:
            print(f"- {o.get('store','').title():15s} : {o.get('price')}  {o.get('title','')}", flush=True)
        if best:
            print(f"=> Cheapest: {best.get('store','').title()} @ {best.get('price')}", flush=True)
            if best.get("url"): print(f"   URL: {best.get('url')}", flush=True)
    else:
        print("\n--- No offers found yet (Walmart+Flipp) ---", flush=True)

    proof_src = None
    if best and best.get("image"):
        proof_src = _download_image(best.get("image") or "")

    with lock_obj:
        entry = history_by_key.get(key)
        if entry:
            if best:
                entry["best_store"] = best.get("store","")
                entry["best_price"] = best.get("price","")
                entry["best_url"] = best.get("url","")
            cap_path = entry.get("capture_path","")
            title = _best_string(entry.get("brand"), entry.get("name"), entry.get("variant"))
            store = (entry.get("best_store") or "").title()
            price_txt = str(entry.get("best_price") or "")
            out_path = str(CAP_DIR / f"proof_{int(time.time())}.png")
            try:
                entry["proof_path"] = make_proof_png(
                    title=title or "(recognizing…)",
                    price_text=price_txt or "—",
                    store=store,
                    url=entry.get("best_url","") or "",
                    camera_path=cap_path,
                    flyer_path=str(proof_src) if proof_src else None,
                    out_path=out_path,
                )
                dprint("Proof composed:", entry["proof_path"])
            except Exception as e:
                dprint("Proof compose error:", e)

            if entry.get("best_url") and not entry.get("opened_url"):
                try:
                    webbrowser.open_new_tab(entry["best_url"])
                    entry["opened_url"] = "yes"
                    dprint("Opened URL:", entry["best_url"])
                except Exception as e:
                    dprint("Open URL error:", e)

        global price_lookup_inflight
        price_lookup_inflight = False
        _write_logs_and_results_page()

def _auto_lock(v: Dict[str, Any], frame_bgr) -> Tuple[str, Path]:
    ts = int(time.time())
    capture_path = CAP_DIR / f"capture_{ts}.jpg"
    cv2.imwrite(str(capture_path), frame_bgr)
    upc = v.get("possible_upc") or ""
    if upc: lock_key = f"UPC:{upc}"
    else:   lock_key = f"VIS:{_prod_key(v)}"
    _beep()
    with lock_obj:
        locked_keys.add(lock_key)
        _ensure_entry(lock_key, v, capture_path)
        _write_logs_and_results_page()
    dprint("LOCK:", lock_key, " -> ", capture_path)
    return lock_key, capture_path

def _vision_worker(country: str):
    dprint("Vision worker started. Country:", country)
    global last_frame_rgb, latest_vision, last_vision_key, vision_hit_count, price_lookup_inflight
    last_scan = 0.0
    while not stop_flag:
        time.sleep(0.02)
        now = time.time()
        if now - last_scan < SCAN_EVERY_SECONDS: continue
        last_scan = now
        with lock_obj:
            frame = None if last_frame_rgb is None else last_frame_rgb.copy()
        if frame is None: 
            continue
        try:
            jpg = _encode_to_jpeg_bytes(frame)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp.write(jpg); tmp.close()
            path = tmp.name
        except Exception as e:
            dprint("JPEG encode error:", e); continue
        try:
            v = identify_product(image=path, country_hint=country)
        except Exception as e:
            dprint("identify_product error:", e); v = None
        if not v: continue
        key = _prod_key(v)
        with lock_obj:
            latest_vision = v
            if key:
                if key == last_vision_key: vision_hit_count += 1
                else: last_vision_key, vision_hit_count = key, 1
                if vision_hit_count >= HITS_NEEDED:
                    lock_id = f"VIS:{key}"
                    if lock_id not in locked_keys:
                        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        lock_key, _ = _auto_lock(v, bgr)
                        _ensure_results_page_opened_once()
                        if not price_lookup_inflight:
                            price_lookup_inflight = True
                            threading.Thread(target=_price_lookup_thread, args=(lock_key, v), daemon=True).start()

def _rotate_frame(rgb: np.ndarray, degrees: int) -> np.ndarray:
    if degrees % 360 == 0:   return rgb
    if degrees % 360 == 90:  return cv2.rotate(rgb, cv2.ROTATE_90_CLOCKWISE)
    if degrees % 360 == 180: return cv2.rotate(rgb, cv2.ROTATE_180)
    if degrees % 360 == 270: return cv2.rotate(rgb, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return rgb

def _ensure_results_page_opened_once():
    global results_page_opened
    if not results_page_opened and RESULTS_HTML.exists():
        try:
            webbrowser.open_new_tab(RESULTS_HTML.resolve().as_uri())
            results_page_opened = True
            dprint("Opened results page:", RESULTS_HTML)
        except Exception as e:
            dprint("Open results page error:", e)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Instant Price Match — DEV hybrid scanner (debug)")
    parser.add_argument("--ip", required=True)
    parser.add_argument("--port", type=int, default=4747)
    parser.add_argument("--country", default="CA")
    parser.add_argument("--store", default="Walmart")
    args = parser.parse_args()

    # Environment diagnostics
    dprint("Python:", sys.version)
    dprint("cv2.__version__:", getattr(cv2, '__version__', '?'))
    key = os.getenv("OPENAI_API_KEY") or ""
    dprint("OPENAI_API_KEY present:", bool(key), "len:", len(key))

    dprint("Opening DroidCam stream...", f"http://{args.ip}:{args.port}/video")
    cap = open_capture(args.ip, args.port)
    dprint("Stream open attempt done. First read...")
    f0 = read_frame_rgb(cap)
    dprint("First frame:", "OK" if f0 is not None else "NONE", "shape:", None if f0 is None else f0.shape)

    threading.Thread(target=_vision_worker, args=(args.country,), daemon=True).start()

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 960, 540)
    cv2.namedWindow(LIST_WINDOW, cv2.WINDOW_AUTOSIZE)
    dprint("Windows created. Entering main loop.")

    global ROTATE_DEG, latest_upc, last_upc, upc_hit_count, price_lookup_inflight
    try:
        while True:
            rgb = read_frame_rgb(cap)
            if rgb is None:
                # keep UI responsive even if no frame
                black = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(black, "No frames from DroidCam…", (20, 180), FONT, 0.8, (255,255,255), 2, cv2.LINE_AA)
                cv2.imshow(WINDOW_NAME, black)
                if cv2.waitKey(20) & 0xFF == 27: break
                continue
            rgb = _rotate_frame(rgb, ROTATE_DEG)
            with lock_obj:
                global last_frame_rgb
                last_frame_rgb = rgb
                v = latest_vision
                vis_key = _prod_key(v or {})

            # Barcode pass
            upc, boxes = decode_upc_from_rgb(rgb)
            latest_upc = upc
            if upc:
                upc_hit_count = upc_hit_count + 1 if upc == last_upc else 1
                last_upc = upc

            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            for (x,y,w,h) in boxes:
                cv2.rectangle(bgr, (x,y), (x+w, y+h), (0,255,0), 2)

            if upc_hit_count >= HITS_NEEDED and f"UPC:{last_upc}" not in locked_keys:
                synth_v = {
                    "brand": v.get("brand","") if v else "",
                    "name":  v.get("name","") if v else "",
                    "variant": v.get("variant","") if v else "",
                    "size_text": v.get("size_text","") if v else "",
                    "possible_upc": last_upc,
                    "notes": "Locked via barcode",
                }
                lock_key, _ = _auto_lock(synth_v, bgr)
                _ensure_results_page_opened_once()
                if not price_lookup_inflight:
                    price_lookup_inflight = True
                    threading.Thread(target=_price_lookup_thread, args=(lock_key, synth_v), daemon=True).start()

            if v:
                info = f"{v.get('brand','')} {v.get('name','')}".strip() or "Recognizing…"
                sub  = f"Variant: {v.get('variant','') or '—'} | Size: {v.get('size_text','') or '—'}"
            else:
                info, sub = "Recognizing…", "Hold front label steady"
            if latest_upc:
                sub += f" | UPC: {latest_upc}"

            hist_key = f"UPC:{latest_upc}" if latest_upc else (f"VIS:{vis_key}" if vis_key else "")
            is_locked = bool(hist_key and hist_key in locked_keys)
            if hist_key and hist_key in history_by_key:
                e = history_by_key[hist_key]
                if e.get("best_price"):
                    sub += f" | Best: {e.get('best_price')} @ {(e.get('best_store') or '').title()}"

            _draw_hud(bgr, info, sub)
            _draw_bottom_check(bgr, is_locked)
            cv2.putText(bgr, "Esc: Quit   |   r: Rotate 90°", (12, bgr.shape[0]-8), FONT, 0.6, (255,255,255), 1, cv2.LINE_AA)

            cv2.imshow(WINDOW_NAME, bgr)
            _render_list_window()

            if hist_key and hist_key in history_by_key:
                proof = history_by_key[hist_key].get("proof_path","")
                if proof and os.path.exists(proof):
                    img = cv2.imread(proof)
                    if img is not None:
                        cv2.imshow(PROOF_WINDOW, img)

            key = cv2.waitKey(1) & 0xFF
            if key == 27: break
            elif key in (ord('r'), ord('R')): ROTATE_DEG = (ROTATE_DEG + 90) % 360

    except Exception as e:
        dprint("FATAL:", e)
        dprint(traceback.format_exc())
        raise
    finally:
        dprint("Shutting down…")
        global stop_flag
        stop_flag = True
        try: cap.release()
        except: pass
        cv2.destroyAllWindows()

def _ensure_results_page_opened_once():
    global results_page_opened
    if not results_page_opened and RESULTS_HTML.exists():
        try:
            webbrowser.open_new_tab(RESULTS_HTML.resolve().as_uri())
            results_page_opened = True
            dprint("Opened results page:", RESULTS_HTML)
        except Exception as e:
            dprint("Open results page error:", e)

if __name__ == "__main__":
    main()
