# ui_price_match.py
# Streamlit UI: DroidCam preview -> capture -> Vision -> Flipp deals -> add best to cart

from __future__ import annotations
import os
import time
from pathlib import Path

import cv2
import numpy as np
import streamlit as st

from tools.vision_identify import identify_product
from tools.flipp_adapter import search_deals

TMP_DIR = Path(".tmp_scans")
TMP_DIR.mkdir(exist_ok=True)

# ---------- camera helpers ----------
def _get_camera():
    return st.session_state.get("camera")

def connect_droidcam(ip: str, port: str):
    """Open DroidCam MJPEG stream http://IP:PORT/video"""
    url = f"http://{ip}:{port}/video"
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        return None, f"Could not open DroidCam at {url}. Open it in a browser first to confirm."
    st.session_state["camera"] = cap
    st.session_state["cam_url"] = url
    return cap, None

def disconnect_camera():
    cap = st.session_state.pop("camera", None)
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass
    st.session_state.pop("cam_url", None)

def read_frame():
    cap = _get_camera()
    if cap is None:
        return None, "Camera not connected"
    ok, frame = cap.read()
    if not ok or frame is None:
        return None, "Failed to read frame. Is DroidCam streaming?"
    return frame, None

# ---------- pipeline ----------
def run_pipeline_from_image(image_bgr, postal: str, country: str, max_results: int = 10):
    """Save temp image, run Vision -> Flipp, return (path, name, deals)."""
    ts = int(time.time() * 1000)
    out_path = TMP_DIR / f"scan_{ts}.jpg"
    cv2.imwrite(str(out_path), image_bgr)

    name = identify_product(image=str(out_path))
    deals = []
    if name:
        deals = search_deals(name, postal=postal, country=country, limit=max_results)
    return str(out_path), name, deals

def deals_table_md(deals: list[dict]) -> str:
    lines = []
    lines.append("| Store | Title | Price | Proof |")
    lines.append("|---|---|---:|---|")
    for d in deals:
        store = d.get("store") or "-"
        title = d.get("title") or "-"
        price = d.get("price")
        price_str = f"${price:0.2f}" if isinstance(price, (int, float)) else "-"
        url = d.get("flyer_url") or ""
        proof = f"[Open]({url})" if url else "-"
        # escape pipes in title
        title = title.replace("|", "\\|")
        lines.append(f"| {store} | {title} | {price_str} | {proof} |")
    return "\n".join(lines)

# ---------- UI ----------
st.set_page_config(page_title="Instant Price Match", layout="wide")
st.title("Instant Price Match — Scan & Price Match")

with st.sidebar:
    st.header("Settings")
    country = st.selectbox("Country", ["CA", "US"], index=0)
    postal = st.text_input("Postal/Zip", value=st.session_state.get("postal", "M5V2T6"))
    st.session_state["postal"] = postal

    st.divider()
    st.subheader("DroidCam")
    dc_ip = st.text_input("Phone IP", value=st.session_state.get("dc_ip", "10.0.0.232"))
    dc_port = st.text_input("Port", value=st.session_state.get("dc_port", "4747"))
    c1, c2 = st.columns(2)
    if c1.button("Connect"):
        cap, err = connect_droidcam(dc_ip.strip(), dc_port.strip())
        if err:
            st.error(err)
        else:
            st.success(f"Connected: {st.session_state['cam_url']}")
        st.session_state["dc_ip"] = dc_ip.strip()
        st.session_state["dc_port"] = dc_port.strip()
    if c2.button("Disconnect"):
        disconnect_camera()
        st.info("Camera disconnected")

    st.divider()
    st.subheader("Or upload a photo")
    uploaded = st.file_uploader("Choose file", type=["jpg", "jpeg", "png", "webp"])
    if uploaded:
        st.session_state["uploaded_bytes"] = uploaded.read()
    else:
        st.session_state.pop("uploaded_bytes", None)

left, right = st.columns([3, 2])

with left:
    st.subheader("Live Preview")
    preview = st.empty()
    btns = st.columns(3)

    if btns[0].button("Refresh Preview"):
        frame, err = read_frame()
        if err:
            st.warning(err)
        else:
            preview.image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), channels="RGB", use_container_width=True)

    if btns[1].button("Capture & Match (Camera)"):
        frame, err = read_frame()
        if err:
            st.warning(err)
        else:
            path, name, deals = run_pipeline_from_image(frame, postal, country, max_results=10)
            st.session_state["last_capture_path"] = path
            st.session_state["last_name"] = name
            st.session_state["last_deals"] = deals
            if name:
                st.success(f"Identified: {name}")
            else:
                st.error("Could not identify product from camera image.")

    if btns[2].button("Match Uploaded Photo"):
        if "uploaded_bytes" not in st.session_state:
            st.info("Upload a photo in the sidebar first.")
        else:
            nparr = np.frombuffer(st.session_state["uploaded_bytes"], np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                st.error("Failed to decode uploaded image.")
            else:
                path, name, deals = run_pipeline_from_image(img, postal, country, max_results=10)
                st.session_state["last_capture_path"] = path
                st.session_state["last_name"] = name
                st.session_state["last_deals"] = deals
                if name:
                    st.success(f"Identified: {name}")
                else:
                    st.error("Could not identify product from uploaded image.")

with right:
    st.subheader("Result")
    name = st.session_state.get("last_name")
    if name:
        st.write(f"**Product:** {name}")

    cap_path = st.session_state.get("last_capture_path")
    if cap_path and os.path.exists(cap_path):
        st.image(cap_path, caption="Last capture", use_container_width=True)

    deals = st.session_state.get("last_deals", [])
    if deals:
        st.markdown(deals_table_md(deals), unsafe_allow_html=True)
        best = min(deals, key=lambda d: d.get("price", 1e12))
        st.markdown(
            f"**Best:** ${best['price']:.2f} at {best.get('store') or '-'} — "
            f"[Proof]({best.get('flyer_url','')})"
        )
        if "cart" not in st.session_state:
            st.session_state["cart"] = []
        if st.button("Add best to Cart"):
            st.session_state["cart"].append({
                "name": name or "Unknown",
                "store": best.get("store"),
                "price": best.get("price"),
                "proof": best.get("flyer_url"),
            })
            st.success("Added to cart.")
    else:
        st.caption("No deals yet. Capture or upload to run matching.")

st.divider()
st.subheader("Cart")
cart = st.session_state.get("cart", [])
if cart:
    st.dataframe(cart, use_container_width=True)
else:
    st.caption("Cart is empty.")
