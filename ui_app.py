# ui_app.py — Instant Price Match (Streamlit UI)
# Persistent DroidCam scanner + running list of scanned items
#
# - Keeps DroidCam open until you press Stop
# - Continuous UPC/EAN decoding with duplicate debounce
# - Each new UPC calls: app.py --upc <code> --country <...>
# - Appends stdout/err (and proof path if detected) to "Scanned Items"
# - Disables PDF417 to stop zbar warnings
# - Uses streamlit-autorefresh for smooth, periodic reruns

import sys, os, io, re, json, subprocess, time
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

import cv2
import numpy as np
from pyzbar.pyzbar import decode as zbar_decode, ZBarSymbol
import streamlit as st
from PIL import Image

# --- optional dependency: streamlit-autorefresh ---
try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    def st_autorefresh(interval: int = 1000, key: str = "refresh", limit: Optional[int] = None):
        st.warning(
            "Install 'streamlit-autorefresh' to enable live scanning refresh:\n"
            "  pip install streamlit-autorefresh",
            icon="⚠️",
        )
        return None

st.set_page_config(page_title="Instant Price Match", layout="wide")

# ---------- Settings & constants ----------
DECODE_SYMBOLS = [
    ZBarSymbol.EAN13,
    ZBarSymbol.EAN8,
    ZBarSymbol.UPCA,
    ZBarSymbol.UPCE,
    ZBarSymbol.CODE128,  # remove if you only want UPC/EAN
]
DEBOUNCE_SECONDS = 5.0
AUTOREFRESH_MS = 80
CAPTURE_TIMEOUT_S = 4.0

# ---------- Session init ----------
def _init_state():
    ss = st.session_state
    ss.setdefault("scanner_running", False)
    ss.setdefault("cap", None)  # cv2.VideoCapture handle
    ss.setdefault("cap_info", {"ip": None, "port": None})
    ss.setdefault("last_upc", None)
    ss.setdefault("last_seen_ts", 0.0)
    ss.setdefault("scans", [])  # list of dicts
    ss.setdefault("last_frame_png", None)

_init_state()

# ---------- Helpers ----------
@dataclass
class CaptureResult:
    rgb: np.ndarray
    url: str

def _bgr_to_rgb(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

def droidcam_url(ip: str, port: int) -> str:
    return f"http://{ip}:{port}/video"

def ensure_cap(ip: str, port: int):
    """Open or reuse the VideoCapture to DroidCam."""
    ss = st.session_state
    need_new = (
        ss["cap"] is None
        or not isinstance(ss["cap"], cv2.VideoCapture)
        or not ss["cap"].isOpened()
        or ss["cap_info"].get("ip") != ip
        or ss["cap_info"].get("port") != port
    )
    if need_new:
        if ss["cap"] is not None:
            try:
                ss["cap"].release()
            except Exception:
                pass
        url = droidcam_url(ip, port)
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ss["cap"] = cap
        ss["cap_info"] = {"ip": ip, "port": port}

def close_cap():
    ss = st.session_state
    if ss["cap"] is not None:
        try:
            ss["cap"].release()
        except Exception:
            pass
    ss["cap"] = None

def read_frame() -> Optional[np.ndarray]:
    ss = st.session_state
    if ss["cap"] is None:
        return None
    ok, frame = ss["cap"].read()
    if not ok or frame is None:
        return None
    return _bgr_to_rgb(frame)

def put_last_frame(pil_img: Image.Image):
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    st.session_state["last_frame_png"] = buf.getvalue()

def get_last_frame_pil() -> Optional[Image.Image]:
    data = st.session_state.get("last_frame_png")
    if data is None:
        return None
    return Image.open(io.BytesIO(data))

def try_decode_upc(img_rgb: np.ndarray) -> Optional[str]:
    """Decode UPC/EAN (and CODE128) with 0/90/180/270 rotations."""
    for k in range(4):
        candidate = np.rot90(img_rgb, k=k) if k else img_rgb
        gray = cv2.cvtColor(candidate, cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        gray = cv2.equalizeHist(gray)
        results = zbar_decode(gray, symbols=DECODE_SYMBOLS)
        if results:
            return results[0].data.decode("utf-8", errors="ignore")
    return None

def run_price_match_upc(upc: str, country: str) -> Tuple[int, str, str, Optional[str], Optional[Dict[str, Any]]]:
    """
    Call app.py --upc and try to parse:
    - proof path from a 'Saved proof to:' line (stdout or stderr)
    - JSON block (if stdout contains JSON)
    """
    cmd = [sys.executable, "app.py", "--upc", upc, "--country", country]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out, err = proc.stdout or "", proc.stderr or ""

    proof = None
    m = re.search(r"Saved proof to:\s*(.+)", out) or re.search(r"Saved proof to:\s*(.+)", err)
    if m:
        proof = m.group(1).strip()

    parsed = None
    try:
        start = out.index("{")
        end = out.rindex("}") + 1
        parsed = json.loads(out[start:end])
    except Exception:
        pass

    return proc.returncode, out, err, proof, parsed

def add_scan(upc: str, country: str, stdout: str, stderr: str, proof: Optional[str], parsed: Optional[Dict[str, Any]]):
    st.session_state["scans"].append({
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "upc": upc,
        "country": country,
        "stdout": stdout,
        "stderr": stderr,
        "proof": proof,
        "parsed": parsed,
    })

# ---------- Sidebar ----------
st.sidebar.header("Settings")
store = st.sidebar.selectbox("Store", ["Walmart", "Other"])
country = st.sidebar.selectbox("Country", ["CA", "US"])
use_droidcam = st.sidebar.checkbox("DEV: Use DroidCam instead of the app camera", value=True)
dc_ip = st.sidebar.text_input("DroidCam IP (e.g., 192.168.1.23)", value="10.0.0.187")
dc_port = st.sidebar.number_input("DroidCam Port", value=4747, step=1)
show_debug = st.sidebar.checkbox("Show debug JSON", value=False)

st.title("Instant Price Match")

# ---------- Layout ----------
col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.subheader("Camera / Upload")

    # One-shot capture
    if use_droidcam:
        if st.button("Take Photo", use_container_width=True):
            ensure_cap(dc_ip.strip(), int(dc_port))
            frame = read_frame()
            if frame is None:
                st.error(f"Could not read a frame from {droidcam_url(dc_ip, int(dc_port))}")
            else:
                pil = Image.fromarray(frame)
                put_last_frame(pil)
                st.success(f"Captured frame from {dc_ip}:{dc_port}")
        last = get_last_frame_pil()
        if last is not None:
            st.image(last, caption="Last captured frame", use_container_width=True)
    else:
        shot = st.camera_input("Take Photo")
        if shot is not None:
            pil = Image.open(shot)
            put_last_frame(pil)
            st.success("Captured from device camera")

    up = st.file_uploader("Upload a file", type=["png", "jpg", "jpeg", "webp"])
    if up is not None:
        pil = Image.open(up)
        put_last_frame(pil)
        st.success("Loaded uploaded image")

with col_right:
    st.subheader("Actions")

    start = st.button("Start Scanner", use_container_width=True, disabled=st.session_state["scanner_running"] is True)
    stop = st.button("Stop Scanner", use_container_width=True, disabled=st.session_state["scanner_running"] is False)

    if start:
        st.session_state["scanner_running"] = True
        ensure_cap(dc_ip.strip(), int(dc_port))
        st.session_state["last_upc"] = None
        st.session_state["last_seen_ts"] = 0.0

    if stop:
        st.session_state["scanner_running"] = False
        close_cap()

    # Live scanning/preview
    frame_box = st.empty()
    status_box = st.empty()

    if st.session_state["scanner_running"]:
        st_autorefresh(interval=AUTOREFRESH_MS, key="scanner_refresh")

        ensure_cap(dc_ip.strip(), int(dc_port))
        frame = read_frame()

        if frame is not None:
            frame_box.image(frame, caption=f"Live scanner ({dc_ip}:{dc_port})", use_container_width=True)

            upc = try_decode_upc(frame)
            now = time.time()

            if upc:
                # Debounce duplicates for a few seconds
                if (upc != st.session_state["last_upc"]) or ((now - st.session_state["last_seen_ts"]) > DEBOUNCE_SECONDS):
                    st.session_state["last_upc"] = upc
                    st.session_state["last_seen_ts"] = now

                    status_box.info(f"UPC detected: {upc} — running price match...")
                    rc, out, err, proof, parsed = run_price_match_upc(upc, country)
                    add_scan(upc, country, out, err, proof, parsed)

                    if rc == 0:
                        status_box.success(f"Completed: {upc}" + (f" — proof: {proof}" if proof else ""))
                    else:
                        status_box.error(f"app.py returned {rc} for {upc}")
                else:
                    remaining = int(max(0, DEBOUNCE_SECONDS - (now - st.session_state["last_seen_ts"])))
                    status_box.write(f"UPC {upc} recently seen; waiting {remaining}s to rescan.")
            else:
                status_box.write("Scanning...")

        else:
            status_box.warning(f"No frame from {droidcam_url(dc_ip, int(dc_port))}. Is DroidCam running?")

# ---------- Scanned items list ----------
st.markdown("---")
st.subheader("Scanned Items")

scans = st.session_state["scans"]
if len(scans) == 0:
    st.caption("No items scanned yet.")
else:
    for i, it in enumerate(reversed(scans), start=1):
        st.markdown(f"**{i}. {it['ts']} — UPC {it['upc']} ({it['country']})**")
        if it.get("parsed") is not None:
            st.code(json.dumps(it["parsed"], indent=2))
        else:
            st.code(it["stdout"] or "(no stdout)")
        if it.get("stderr"):
            with st.expander("stderr"):
                st.code(it["stderr"])
        if it.get("proof"):
            st.caption(f"Proof: {it['proof']}")

colc1, colc2 = st.columns([1,1])
with colc1:
    if st.button("Clear Scans"):
        st.session_state["scans"] = []
with colc2:
    if st.button("Release Camera"):
        close_cap()
        st.success("Camera released.")

# ---------- Debug ----------
if show_debug:
    st.write("Debug")
    st.json({
        "scanner_running": st.session_state["scanner_running"],
        "cap_open": (st.session_state["cap"] is not None and isinstance(st.session_state["cap"], cv2.VideoCapture) and st.session_state["cap"].isOpened()),
        "cap_info": st.session_state["cap_info"],
        "last_upc": st.session_state["last_upc"],
        "scans_count": len(st.session_state["scans"]),
    })
