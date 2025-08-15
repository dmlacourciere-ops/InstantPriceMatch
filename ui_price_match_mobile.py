# ui_price_match_mobile.py
# Streamlit UI (phone camera): open on your phone via Network URL, capture -> Vision -> Flipp -> Cart

from __future__ import annotations
import os
import time
from pathlib import Path
from typing import List, Dict, Optional

import streamlit as st

from tools.vision_identify import identify_product
from tools.flipp_adapter import search_deals

TMP_DIR = Path(".tmp_scans")
TMP_DIR.mkdir(exist_ok=True)


def _norm(s: Optional[str]) -> str:
    return " ".join((s or "").split())


def _save_upload_to_file(upload) -> str:
    """Write uploaded/camera bytes to a temp jpg and return the path."""
    ts = int(time.time() * 1000)
    out = TMP_DIR / f"scan_{ts}.jpg"
    data = upload.getvalue()
    out.write_bytes(data)
    return str(out)


def deals_table_md(deals: List[Dict]) -> str:
    lines = []
    lines.append("| Store | Title | Price | Proof |")
    lines.append("|---|---|---:|---|")
    for d in deals:
        store = d.get("store") or "-"
        title = (d.get("title") or "-").replace("|", "\\|")
        price = d.get("price")
        price_str = f"${float(price):.2f}" if isinstance(price, (int, float)) else "-"
        url = d.get("flyer_url") or ""
        proof = f"[Open]({url})" if url else "-"
        lines.append(f"| {store} | {title} | {price_str} | {proof} |")
    return "\n".join(lines)


st.set_page_config(page_title="Instant Price Match (Phone Camera)", layout="wide")
st.title("Instant Price Match — Phone Camera")

with st.sidebar:
    st.header("How to use")
    st.write(
        "1) Start the app on your PC.\n"
        "2) On your phone, open the **Network URL** shown in the terminal.\n"
        "3) Allow camera access when prompted.\n"
        "4) Point at the product, tap **Take Photo**, then **Match Photo**."
    )
    st.divider()
    st.header("Settings")
    country = st.selectbox("Country", ["CA", "US"], index=0)
    postal = st.text_input("Postal/Zip", value=st.session_state.get("postal", "M5V2T6"))
    st.session_state["postal"] = postal

left, right = st.columns([3, 2])

with left:
    st.subheader("Phone Camera")
    # This shows a live preview and a shutter button on the phone
    img = st.camera_input("Point at product and tap 'Take Photo'")

    c1, c2 = st.columns(2)
    if c1.button("Match Photo"):
        if img is None:
            st.warning("Take a photo first.")
        else:
            img_path = _save_upload_to_file(img)
            name = identify_product(image=img_path)
            deals = search_deals(name, postal=postal, country=country, limit=12) if name else []
            st.session_state["last_img"] = img_path
            st.session_state["last_name"] = name
            st.session_state["last_deals"] = deals
            if name:
                st.success(f"Identified: {name}")
            else:
                st.error("Could not identify product from photo. Try again closer/brighter.")

    if c2.button("Clear Result"):
        for k in ["last_img", "last_name", "last_deals"]:
            st.session_state.pop(k, None)
        st.info("Cleared.")

with right:
    st.subheader("Result")
    name = st.session_state.get("last_name")
    if name:
        st.write(f"**Product:** {name}")

    img_path = st.session_state.get("last_img")
    if img_path and os.path.exists(img_path):
        st.image(img_path, caption="Last capture", use_container_width=True)

    deals = st.session_state.get("last_deals", [])
    if deals:
        st.markdown(deals_table_md(deals), unsafe_allow_html=True)
        best = min(deals, key=lambda d: d.get("price", 1e12))
        st.markdown(
            f"**Best:** ${best['price']:.2f} at {best.get('store') or '-'} — "
            f"[Proof]({best.get('flyer_url','')})"
        )
        # simple cart
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
        st.caption("No deals yet. Take a photo and press Match Photo.")

st.divider()
st.subheader("Cart")
cart = st.session_state.get("cart", [])
if cart:
    st.dataframe(cart, use_container_width=True)
else:
    st.caption("Cart is empty.")
