# ui_app.py — Camera UI for Instant Price Match (prod camera + dev DroidCam)
import io
import os
import sys
import json
import tempfile
from typing import Any, Dict, List, Optional

import streamlit as st
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for p in (BASE_DIR, os.path.join(BASE_DIR, "tools"), os.path.join(BASE_DIR, "providers")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.vision_identify import identify_product
try:
    from tools import walmart_adapter as WAL
except Exception:
    WAL = None  # type: ignore

# DEV CAMERA
try:
    from tools.droidcam import grab_frame as droidcam_grab_frame
except Exception:
    droidcam_grab_frame = None  # type: ignore

def _best_string(*parts: Optional[str]) -> str:
    return " ".join([p.strip() for p in parts if isinstance(p, str) and p.strip()])

def _as_price(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return float("inf")

def _summarize_offers(offers: List[Dict[str, Any]]) -> Dict[str, Any]:
    offers_sorted = sorted(offers, key=lambda x: _as_price(x.get("price")))
    cheapest = offers_sorted[0] if offers_sorted else None
    return {"count": len(offers_sorted), "cheapest": cheapest, "offers": offers_sorted}

def _search_walmart(upc: Optional[str], name_guess: Optional[str]) -> List[Dict[str, Any]]:
    if WAL is None:
        return []
    try:
        return WAL.lookup_by_upc_or_name(upc=upc, name=name_guess)
    except Exception:
        return []

def _save_uploaded_image(upload) -> Optional[str]:
    if not upload:
        return None
    try:
        img = Image.open(upload).convert("RGB")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        img.save(tmp.name, format="JPEG", quality=92)
        return tmp.name
    except Exception:
        return None

def main():
    st.set_page_config(page_title="Instant Price Match", page_icon="💸", layout="centered")
    st.title("📷 Instant Price Match")

    with st.sidebar:
        st.header("Settings")
        store_in = st.selectbox("Store I’m in", ["Walmart", "Best Buy", "Home Depot", "Other"], index=0)
        country = st.selectbox("Country", ["CA", "US"], index=0)
        dev_use_droidcam = st.checkbox("DEV: Use DroidCam instead of the app camera", value=False)
        droid_ip = st.text_input("DroidCam IP (e.g., 192.168.1.23)", value="", disabled=not dev_use_droidcam)
        droid_port = st.number_input("DroidCam Port", value=4747, step=1, disabled=not dev_use_droidcam)
        show_debug = st.checkbox("Show debug JSON", value=False)
        st.markdown("---")
        st.caption("End users use the app camera. DroidCam is dev-only for testing camera flow.")

    img_path: Optional[str] = None

    if dev_use_droidcam:
        st.subheader("DEV CAMERA (DroidCam)")
        st.write("Open DroidCam on your phone and ensure http://IP:PORT/shot.jpg works in a browser.")
        if st.button("Grab frame from DroidCam"):
            if not droid_ip.strip():
                st.error("Enter the phone’s IP first.")
            elif droidcam_grab_frame is None:
                st.error("DroidCam helper missing. Did you create tools/droidcam.py?")
            else:
                try:
                    img_path = droidcam_grab_frame(droid_ip.strip(), int(droid_port))
                    st.success(f"Captured frame from {droid_ip}:{droid_port}")
                    st.image(img_path, caption="DroidCam frame", use_container_width=True)
                except Exception as e:
                    st.error(f"Could not capture from DroidCam: {e}")
    else:
        st.subheader("Camera / Upload")
        cam = st.camera_input("Use camera", label_visibility="collapsed")
        file = st.file_uploader("...or upload a file", type=["png", "jpg", "jpeg", "webp"])
        img_path = _save_uploaded_image(cam or file)

    run_clicked = st.button("Run Vision", type="primary")

    if run_clicked:
        if not img_path:
            st.warning("Capture or upload an image first.")
            return

        with st.spinner("Identifying product…"):
            try:
                vision = identify_product(image=img_path, country_hint=country)
            except Exception as e:
                st.error(f"Vision error: {e}")
                return

        st.success("Product identified")
        if show_debug:
            st.json(vision)
        else:
            st.write(
                f"**Brand:** {vision.get('brand','')}  \n"
                f"**Name:** {vision.get('name','')}  \n"
                f"**Variant:** {vision.get('variant','')}  \n"
                f"**Size:** {vision.get('size_text','')}  \n"
                f"**Possible UPC:** {vision.get('possible_upc','') or '—'}"
            )

        upc = vision.get("possible_upc") or None
        name_guess = _best_string(vision.get("brand"), vision.get("name"), vision.get("variant"), vision.get("size_text")) or None

        with st.spinner("Searching stores…"):
            walmart = _search_walmart(upc, name_guess)

        all_offers = [{"store": "walmart", **o} for o in (walmart or [])]
        if not all_offers:
            st.warning("No offers found yet (currently only Walmart wired).")
            return

        summary = _summarize_offers(all_offers)
        cheapest = summary["cheapest"]

        st.markdown("### Best offer")
        st.write(
            f"**Source:** {cheapest.get('store','').title() if cheapest else '—'}  \n"
            f"**Title:** {cheapest.get('title','') if cheapest else '—'}  \n"
            f"**Price:** {cheapest.get('price','') if cheapest else '—'}  \n"
            f"**URL:** {cheapest.get('url','') if cheapest else '—'}"
        )

        st.markdown("---")
        st.markdown("### Cashier-proof summary")
        st.write(
            f"You are in **{store_in}**.\n\n"
            f"- **Product:** {_best_string(vision.get('brand'), vision.get('name'))} {vision.get('variant','')} {vision.get('size_text','')}\n"
            f"- **Lowest competitor price:** {cheapest.get('price','—') if cheapest else '—'}\n"
            f"- **Source:** {(cheapest.get('store','').title() if cheapest else '—')}\n"
            f"- **Link:** {(cheapest.get('url','') if cheapest else '—')}"
        )

        if show_debug:
            st.markdown("#### All offers (raw)")
            st.json(summary)

if __name__ == "__main__":
    main()
