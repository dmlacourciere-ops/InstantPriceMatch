from __future__ import annotations
import argparse, json, webbrowser
from pathlib import Path
import concurrent.futures as cf
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
from PIL import Image

# === Paths ===
IMAGES_DIR = Path("images")           # where downloaded imgs live
EMB_DIR    = Path("embeddings")       # where we'll save vectors+meta
SETTINGS_PATH = Path("settings.json")

IMAGES_DIR.mkdir(exist_ok=True)
EMB_DIR.mkdir(exist_ok=True)

# === CSV Loader ===
def _load_df(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    for c in ["barcode","product_name","image_url"]:
        if c not in df.columns:
            raise RuntimeError(f"CSV missing required column: {c}")
    df = df[df["image_url"].astype(str).str.len() > 6].copy()
    df["barcode"] = df["barcode"].astype(str).str.replace(r"\D","",regex=True)
    df["product_name"] = df["product_name"].fillna("").astype(str)
    return df

def _pick_local_image_path(code: str) -> Path|None:
    for ext in (".jpg",".jpeg",".png",".webp"):
        p = IMAGES_DIR / f"{code}{ext}"
        if p.exists():
            return p
    return None

# === Download ===
def _download_one(row: pd.Series, timeout=20) -> tuple[str,bool]:
    import requests
    code = row["barcode"]
    url  = str(row["image_url"])

    candidates = []
    if url.startswith("http"):
        # Prefer the v2 CDN first (much more reliable)
        # OFF v2 pattern: https://images.openfoodfacts.org/v2/product/{barcode}/front/400.jpg
        candidates.append(f"https://images.openfoodfacts.org/v2/product/{code}/front/400.jpg")
        # fallback sizes/langs
        for size in (400, 200, 100):
            candidates.append(f"https://images.openfoodfacts.org/v2/product/{code}/front/{size}.jpg")
        # last-resort: whatever CSV had (v1)
        candidates.append(url)
        if url.endswith(".400.jpg"):
            candidates.append(url[:-8] + ".jpg")

    for u in candidates:
        try:
            r = requests.get(u, timeout=timeout, stream=True)
            if r.status_code == 200 and int(r.headers.get("Content-Length", "0")) > 1000:
                ext = ".jpg"
                ct = r.headers.get("Content-Type","").lower()
                if "png" in ct: ext = ".png"
                if "webp" in ct: ext = ".webp"
                out = IMAGES_DIR / f"{code}{ext}"
                with open(out, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk: f.write(chunk)
                return (code, True)
        except Exception:
            pass
    return (code, False)

def run_download(df: pd.DataFrame, limit: int, workers: int):
    rows = df.head(limit).copy() if limit else df.copy()

    # build a plain LIST of Series needing download
    need: list[pd.Series] = []
    for _, r in rows.iterrows():
        code = r["barcode"]
        if not _pick_local_image_path(code):
            need.append(r)

    print(f"[dl] to download now: {len(need)}")
    ok = fail = 0
    if not need:
        print("[dl] nothing to do."); return

    # FIX: iterate the list, not .iterrows()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_download_one, r) for r in need]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            code, good = fut.result()
            ok += 1 if good else 0
            fail += 0 if good else 1
            if i % 200 == 0:
                print(f"[dl] progress: {i}/{len(need)} | ok={ok} fail={fail}")
    print(f"[dl] done — ok: {ok} | failed: {fail}")

# === Embedding ===
def _load_clip():
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    model.eval()
    return model, preprocess

def run_embed(df: pd.DataFrame, limit: int):
    import torch
    model, preprocess = _load_clip()
    rows = df.head(limit).copy() if limit else df.copy()
    items = []
    for _, r in rows.iterrows():
        code = r["barcode"]
        p = _pick_local_image_path(code)
        if p:
            items.append((code, r["product_name"], p))
    if not items:
        print("[embed] no local images found."); return

    feats = []
    metas = []
    batch = []
    B = 32
    with torch.no_grad():
        for i, (code, name, p) in enumerate(items, 1):
            try:
                img = Image.open(p).convert("RGB")
                x = preprocess(img).unsqueeze(0)
                batch.append((code, name, p, x))
            except Exception:
                continue
            if len(batch) == B or i == len(items):
                X = torch.cat([b[3] for b in batch], dim=0)
                f = model.encode_image(X)
                f = f / f.norm(dim=-1, keepdim=True)
                feats.append(f.cpu().numpy())
                for (code, name, pth, _) in batch:
                    metas.append((code, name, str(pth)))
                batch = []
    V = np.concatenate(feats, axis=0) if feats else np.zeros((0,512), dtype=np.float32)
    meta_df = pd.DataFrame(metas, columns=["barcode","product_name","image_path"])
    np.save(EMB_DIR / "clip_vectors.npy", V.astype(np.float32))
    meta_df.to_parquet(EMB_DIR / "clip_meta.parquet", index=False)
    print(f"[embed] saved vectors: {V.shape}")
    print(f"[embed] saved meta: {len(meta_df)}")

# === Search ===
def _embed_image(model, preprocess, img_path: Path):
    import torch
    img = Image.open(img_path).convert("RGB")
    with torch.no_grad():
        t = preprocess(img).unsqueeze(0)
        f = model.encode_image(t)
        f = f / f.norm(dim=-1, keepdim=True)
        return f[0].cpu().numpy()

def match_image(image_path: str, topk=5):
    model, preprocess = _load_clip()
    vec_p = EMB_DIR / "clip_vectors.npy"
    meta_p = EMB_DIR / "clip_meta.parquet"
    if not vec_p.exists() or not meta_p.exists():
        raise RuntimeError("Missing embeddings. Run download+embed first.")
    V = np.load(vec_p)
    M = pd.read_parquet(meta_p)
    q = _embed_image(model, preprocess, Path(image_path))
    sims = V @ q
    if sims.size == 0: return []
    topk = min(topk, sims.shape[0])
    idx = np.argpartition(-sims, topk-1)[:topk]
    idx = idx[np.argsort(-sims[idx])]
    out = []
    for rank, i in enumerate(idx, start=1):
        row = M.iloc[int(i)]
        out.append({
            "rank": rank,
            "score": float(sims[i]),
            "barcode": str(row.get("barcode","")),
            "product_name": str(row.get("product_name","")),
            "image_path": str(row.get("image_path","")),
        })
    return out

# === Menu ===
def get_postal():
    if SETTINGS_PATH.exists():
        try:
            s = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            pc = s.get("postal_code","").replace(" ","")
            if pc: return pc
        except: pass
    return input("Enter your postal code (no spaces, e.g., N6C1E7): ").strip().replace(" ","")

def run_menu():
    print("\n=== Visual Match (photo → product → flyer URL) ===")
    img = input("Path to a product photo (jpg/png/webp): ").strip('"').strip()
    p = Path(img)
    if not p.exists():
        print("File not found:", img); return
    try:
        results = match_image(img, topk=5)
    except Exception as e:
        print("\n[error] Visual index not ready. First run:")
        print("  python instant_price_match.py --mode download --limit 500 --workers 6")
        print("  python instant_price_match.py --mode embed --limit 500")
        print("Details:", e)
        return
    if not results:
        print("No matches. Try a clearer photo."); return
    print("\nTop matches:")
    for r in results:
        name = (r["product_name"] or "").strip()
        print(f" {r['rank']}) score={r['score']:.3f} | [{r['barcode']}] {name[:70]}")
    choice = input("\nPick one (1-5) or Enter to cancel: ").strip()
    if not choice: return
    try:
        r = results[int(choice)-1]
    except:
        print("Invalid choice."); return
    postal = get_postal()
    q = r["product_name"] or r["barcode"]
    url = f"https://flipp.com/en-ca/search/{quote_plus(q)}?postal_code={postal}"
    print("\nFlyer link:", url)
    try:
        import pyperclip; pyperclip.copy(url)
        print("[info] Copied URL to clipboard.")
    except: pass
    try:
        webbrowser.open(url)
        print("[info] Opened flyer in your browser.")
    except: pass

# === Main ===
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["download","embed","both","menu"], default="menu")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=min(8, (__import__('os').cpu_count() or 4)))
    ap.add_argument("--csv", type=str, default=str(Path(r"F:\Docs\off_data\latest\off_canada_products.csv")))
    args = ap.parse_args()

    if args.mode in ("download","both"):
        df = _load_df(Path(args.csv))
        run_download(df, args.limit, args.workers)
    if args.mode in ("embed","both"):
        df = _load_df(Path(args.csv))
        run_embed(df, args.limit)
    if args.mode == "menu":
        run_menu()