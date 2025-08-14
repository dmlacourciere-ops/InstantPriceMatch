#!/usr/bin/env python3
import argparse, csv, os, re, sys, time, json, math, shutil, hashlib
from pathlib import Path
from typing import List, Optional, Tuple
import concurrent.futures as cf

import requests
from requests.adapters import HTTPAdapter, Retry
from tqdm import tqdm

# Optional: only needed for --mode embed / both
EMBED_OK = True
try:
    import numpy as np
    import torch
    import open_clip
    from PIL import Image
except Exception:
    EMBED_OK = False

# ---- Paths ----
PROJECT = Path(__file__).resolve().parent
LATEST_CSV = Path(r"F:\Docs\off_data\latest\off_canada_products.csv")  # adjust if needed
DATA_DIR = PROJECT / "visual_index"
IMG_DIR = DATA_DIR / "images"
EMB_PATH = DATA_DIR / "embeddings.npz"
CATALOG_CSV = DATA_DIR / "catalog.csv"

IMG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

OFF_IMG_BASE = "https://images.openfoodfacts.org/images/products"

# ---- Helpers ----
def _chunk_barcode(bc: str) -> str:
    # OFF stores images under grouped folders (3/3/3/…/rest)
    parts = [bc[max(i-3,0):i] for i in range(len(bc), 0, -3)]
    parts.reverse()
    joined = "/".join(parts)
    return joined

FALLBACK_FILES = [
    "front_en.400.jpg",
    "front_fr.400.jpg",
    "front.400.jpg",
    "1.400.jpg",
    "1.jpg",
    "front_en.jpg",
    "front_fr.jpg",
    "front.jpg",
]

def off_candidates(barcode: str) -> List[str]:
    bc = re.sub(r"\D", "", barcode or "")
    if not bc:
        return []
    p = _chunk_barcode(bc)
    return [f"{OFF_IMG_BASE}/{p}/{name}" for name in FALLBACK_FILES]

def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=3, backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"]
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": "InstantPriceMatch/1.0 (+noncommercial; testing)"})
    return s

def read_rows(limit: Optional[int]) -> List[dict]:
    if not LATEST_CSV.exists():
        print(f"[error] CSV not found: {LATEST_CSV}")
        sys.exit(1)
    rows = []
    with LATEST_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows

def dl_one(row: dict, session: requests.Session, timeout: int = 10) -> Tuple[bool, Optional[str]]:
    bc = (row.get("barcode") or "").strip()
    if not bc:
        return False, None

    # final image path (jpg) by barcode
    out_path = IMG_DIR / f"{bc}.jpg"
    if out_path.exists() and out_path.stat().st_size > 0:
        return True, str(out_path)

    # Try provided image_url first (if looks like OFF)
    url = (row.get("image_url") or "").strip()
    cand_urls = []
    if url.startswith("http"):
        cand_urls.append(url)
    cand_urls.extend(off_candidates(bc))

    for u in cand_urls:
        try:
            r = session.get(u, stream=True, timeout=timeout)
            if r.status_code == 200 and r.headers.get("Content-Type","").lower().startswith("image/"):
                tmp = out_path.with_suffix(".part")
                with open(tmp, "wb") as w:
                    for chunk in r.iter_content(1024 * 32):
                        if chunk:
                            w.write(chunk)
                # small sanity check
                if tmp.stat().st_size > 1024:  # >1KB
                    tmp.replace(out_path)
                    return True, str(out_path)
                else:
                    tmp.unlink(missing_ok=True)
        except Exception:
            continue

    return False, None

def download_images(rows: List[dict], workers: int = 8) -> Tuple[int,int,int]:
    session = make_session()
    ok = 0; fail = 0; skip = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = []
        for row in rows:
            bc = (row.get("barcode") or "").strip()
            if not bc:
                fail += 1
                continue
            out = IMG_DIR / f"{bc}.jpg"
            if out.exists() and out.stat().st_size > 0:
                skip += 1
                continue
            futures.append(ex.submit(dl_one, row, session))
        for fut in tqdm(cf.as_completed(futures), total=len(futures), desc="[dl]"):
            try:
                ok1, _ = fut.result()
                if ok1: ok += 1
                else: fail += 1
            except Exception:
                fail += 1
    return ok, skip, fail

# ---- Embeddings ----
def embed_images(rows: List[dict], device: str = "cpu"):
    if not EMBED_OK:
        print("[error] embedding deps missing. Install: pip install open-clip-torch pillow numpy")
        sys.exit(1)

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    model = model.to(device).eval()
    tokenizer = open_clip.get_tokenizer("ViT-B-32")

    catalog = []
    images = []
    ids = []

    for row in tqdm(rows, desc="[embed] collect"):
        bc = (row.get("barcode") or "").strip()
        if not bc: continue
        img_path = IMG_DIR / f"{bc}.jpg"
        if not img_path.exists(): continue
        try:
            img = Image.open(img_path).convert("RGB")
            images.append(preprocess(img))
            ids.append(bc)
            catalog.append({
                "barcode": bc,
                "product_name": row.get("product_name",""),
                "brand": row.get("brand",""),
                "quantity": row.get("quantity",""),
                "img_path": str(img_path),
            })
        except Exception:
            continue

    if not images:
        print("[error] no images on disk to embed.")
        sys.exit(1)

    batch = 256
    all_emb = []
    with torch.inference_mode():
        for i in tqdm(range(0, len(images), batch), desc="[embed] encode"):
            x = torch.stack(images[i:i+batch]).to(device)
            feats = model.encode_image(x)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            all_emb.append(feats.cpu().numpy())

    embs = np.concatenate(all_emb, axis=0)
    np.savez_compressed(EMB_PATH, embeddings=embs, ids=np.array(ids))
    # write catalog
    with CATALOG_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["barcode","product_name","brand","quantity","img_path"])
        w.writeheader()
        for row in catalog:
            w.writerow(row)

    print(f"[done] embeddings: {embs.shape} → {EMB_PATH}")
    print(f"[done] catalog: {len(catalog)} rows → {CATALOG_CSV}")

# ---- CLI ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["download","embed","both"], default="both")
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--device", type=str, default="cpu")
    args = ap.parse_args()

    rows = read_rows(args.limit)
    print(f"[info] using rows: {len(rows)}")

    if args.mode in ("download","both"):
        ok, skip, fail = download_images(rows, workers=args.workers)
        print(f"[dl] ok: {ok} | skipped: {skip} | failed: {fail}")
        if ok == 0 and skip == 0:
            print("[warn] no images downloaded — check network or URL patterns.")
    if args.mode in ("embed","both"):
        embed_images(rows, device=args.device)

if __name__ == "__main__":
    main()
