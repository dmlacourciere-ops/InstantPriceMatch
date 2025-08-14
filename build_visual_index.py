# build_visual_index.py
# Rebuilds a CLIP visual index from your OFF CSV.
# - Download product images (with robust v2/legacy fallbacks)
# - Embed images with OpenCLIP (CPU, CUDA, or DirectML "dml")
# - Save metadata + embeddings; optionally build an Annoy index if available

from __future__ import annotations
import os, io, sys, time, math, json, shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional

import pandas as pd
import numpy as np
import requests
from PIL import Image

# ---------- paths & config ----------
CSV_LATEST   = Path(r"F:\Docs\off_data\latest\off_canada_products.csv")  # your rebuilt CSV with image_url
IMAGES_DIR   = Path("images")
EMBED_DIR    = Path("embeddings")
FEATS_NPY    = EMBED_DIR / "clip_feats.npy"        # float32 [N,512]
META_PARQUET = EMBED_DIR / "clip_meta.parquet"     # rows aligned with FEATS_NPY
ANNOY_INDEX  = EMBED_DIR / "clip_index.ann"        # optional (skipped if annoy not present)

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
EMBED_DIR.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "InstantPriceMatch/0.1 (+local)"}
TIMEOUT = 20

# ---------- helpers ----------
def _seg(code: str) -> str:
    # OFF "legacy" segmented path e.g. 001/111/002/0758
    return f"{code[0:3]}/{code[3:6]}/{code[6:9]}/{code[9:]}" if len(code) > 9 else code

def _candidate_urls(code: str) -> List[str]:
    # New v2 endpoints first, then legacy
    return [
        f"https://images.openfoodfacts.org/v2/product/{code}/front/400.jpg",
        f"https://images.openfoodfacts.org/v2/product/{code}/front/full.jpg",
        f"https://images.openfoodfacts.org/v2/product/{code}/front/200.jpg",
        f"https://images.openfoodfacts.org/v2/product/{code}/front/100.jpg",
        f"https://images.openfoodfacts.org/images/products/{_seg(code)}/front_en.400.jpg",
        f"https://images.openfoodfacts.org/images/products/{_seg(code)}/front.400.jpg",
        f"https://images.openfoodfacts.org/images/products/{_seg(code)}/front_en.200.jpg",
        f"https://images.openfoodfacts.org/images/products/{_seg(code)}/front.200.jpg",
        f"https://images.openfoodfacts.org/images/products/{_seg(code)}/front_en.100.jpg",
        f"https://images.openfoodfacts.org/images/products/{_seg(code)}/front.100.jpg",
    ]

def _safe_imopen(b: bytes) -> Optional[Image.Image]:
    try:
        im = Image.open(io.BytesIO(b))
        im = im.convert("RGB")
        return im
    except Exception:
        return None

# ---------- CSV loader ----------
def read_csv(limit: int = 0) -> pd.DataFrame:
    if not CSV_LATEST.exists():
        raise FileNotFoundError(f"CSV not found: {CSV_LATEST}")
    df = pd.read_csv(CSV_LATEST)
    # normalize columns we need
    if "barcode" not in df.columns:
        if "code" in df.columns:
            df = df.rename(columns={"code": "barcode"})
        else:
            df["barcode"] = ""
    if "product_name" not in df.columns:
        df["product_name"] = ""
    if "image_url" not in df.columns:
        df["image_url"] = ""
    if limit and limit > 0:
        df = df.head(limit)
    return df

# ---------- DOWNLOADER ----------
def _download_one(row) -> Tuple[str, bool]:
    code = str(row.get("barcode") or "").strip()
    if not code:
        return "", False
    out = IMAGES_DIR / f"{code}.jpg"
    if out.exists():
        return code, True  # already on disk
    # try provided image_url first if present
    first_urls = []
    url = str(row.get("image_url") or "").strip()
    if url:
        first_urls.append(url)
    urls = first_urls + _candidate_urls(code)

    for u in urls:
        try:
            r = requests.get(u, timeout=TIMEOUT, headers=UA)
            if r.status_code == 200 and len(r.content) > 4096:
                im = _safe_imopen(r.content)
                if im is None:
                    continue
                im.save(out, format="JPEG", quality=92)
                return code, True
        except Exception:
            pass
    return code, False

def run_download(df: pd.DataFrame, limit: int, workers: int) -> None:
    rows = df if limit <= 0 else df.head(limit)
    to_get = rows.to_dict(orient="records")
    ok = fail = 0
    total = len(to_get)
    print(f"[dl] to download now: {total}")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(_download_one, r) for r in to_get]
        done = 0
        for f in as_completed(futs):
            _, success = f.result()
            done += 1
            if success: ok += 1
            else:       fail += 1
            if done % 200 == 0 or done == total:
                print(f"[dl] progress: {done}/{total} | ok={ok} fail={fail}")
    print(f"[dl] done — ok: {ok} | failed: {fail}")

# ---------- EMBEDDING ----------
def _load_clip(device: str):
    """
    device: 'cpu' | 'cuda' | 'dml'
    DirectML note:
      we *must* create device via torch_directml.device(), not torch.device('dml')
    """
    import torch
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    model.eval()

    if device == "dml":
        import torch_directml  # ← DirectML bridge
        dev = torch_directml.device()  # returns 'privateuseone:0' under the hood
    else:
        dev = torch.device(device)

    model.to(dev)
    return model, preprocess, dev

def _iter_existing(df: pd.DataFrame) -> List[Tuple[str, str, Path]]:
    """
    Return [(barcode, product_name, image_path)] for images present on disk.
    """
    out = []
    for _, r in df.iterrows():
        code = str(r.get("barcode") or "").strip()
        if not code: 
            continue
        p = IMAGES_DIR / f"{code}.jpg"
        if p.exists():
            out.append((code, str(r.get("product_name", "")), p))
    return out

def run_embed(df: pd.DataFrame, device: str = "cpu", batch: int = 32, nice_ms: int = 0) -> None:
    items = _iter_existing(df)
    if not items:
        print("[emb] nothing to embed (no images found). Run download first.")
        return

    print(f"[emb] to embed now: {len(items):,} (using device: {device})")
    model, preprocess, dev = _load_clip(device)

    import torch
    feats_all = []
    meta_rows = []

    def _flush_batch(imgs: List[Image.Image]):
        if not imgs:
            return None
        with torch.no_grad():
            t = torch.stack([preprocess(im) for im in imgs]).to(dev)
            f = model.encode_image(t)
            f = f / f.norm(dim=-1, keepdim=True)
            return f.detach().cpu().numpy().astype("float32")

    batch_imgs: List[Image.Image] = []
    batch_codes: List[str] = []
    batch_names: List[str] = []
    done = 0
    total = len(items)

    for code, name, path in items:
        try:
            im = Image.open(path).convert("RGB")
        except Exception:
            continue
        batch_imgs.append(im)
        batch_codes.append(code)
        batch_names.append(name)

        if len(batch_imgs) >= batch:
            arr = _flush_batch(batch_imgs)
            if arr is not None:
                feats_all.append(arr)
                for c, n in zip(batch_codes, batch_names):
                    meta_rows.append({"barcode": c, "product_name": n, "image_path": str(IMAGES_DIR / f"{c}.jpg")})
            done += len(batch_imgs)
            if done % 512 == 0 or done >= total:
                print(f"[emb] progress: {done}/{total}")
            batch_imgs.clear(); batch_codes.clear(); batch_names.clear()
            if nice_ms > 0:
                time.sleep(nice_ms / 1000.0)

    # tail
    if batch_imgs:
        arr = _flush_batch(batch_imgs)
        if arr is not None:
            feats_all.append(arr)
            for c, n in zip(batch_codes, batch_names):
                meta_rows.append({"barcode": c, "product_name": n, "image_path": str(IMAGES_DIR / f"{c}.jpg")})
        done += len(batch_imgs)
        print(f"[emb] progress: {done}/{total}")

    if not feats_all:
        print("[emb] nothing embedded.")
        return

    feats = np.concatenate(feats_all, axis=0)
    pd.DataFrame(meta_rows).to_parquet(META_PARQUET, index=False)
    np.save(FEATS_NPY, feats)
    print(f"[save] feats: {feats.shape} -> {FEATS_NPY}")
    print(f"[save] meta rows: {len(meta_rows)} -> {META_PARQUET}")

    # Optional: build Annoy index
    try:
        import annoy  # requires MSVC build tools on Windows; skip if missing
        dim = feats.shape[1]
        idx = annoy.AnnoyIndex(dim, "angular")
        for i in range(feats.shape[0]):
            idx.add_item(i, feats[i].tolist())
        idx.build(50)
        idx.save(str(ANNOY_INDEX))
        print(f"[annoy] saved: {ANNOY_INDEX}")
    except Exception as e:
        print(f"[annoy] skipped (module missing or build tools not present). You can install 'annoy' later. ({e})")

# ---------- CLI ----------
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["download","embed","both"], default="both")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--device", choices=["cpu","cuda","dml"], default="cpu",
                    help="cpu | cuda (NVIDIA) | dml (AMD/Intel via DirectML)")
    ap.add_argument("--batch", type=int, default=32, help="embed batch size")
    ap.add_argument("--nice", type=int, default=0, help="sleep ms per image batch (reduce system load)")
    args = ap.parse_args()

    print(f"Loading: {CSV_LATEST}")
    df = read_csv(args.limit if args.limit > 0 else 0)

    if args.mode in ("download","both"):
        run_download(df, args.limit, args.workers)

    if args.mode in ("embed","both"):
        run_embed(df, device=args.device, batch=args.batch, nice_ms=args.nice)

if __name__ == "__main__":
    main()
