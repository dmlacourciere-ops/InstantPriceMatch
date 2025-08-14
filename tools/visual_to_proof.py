import argparse
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
import torch

# Ensure project root import
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.make_pro_proof import make_pdf

EMB_DIR = ROOT / "embeddings"
FEATS_NPY = EMB_DIR / "clip_feats.npy"
NORM_FEATS = EMB_DIR / "clip_feats_norm.npy"
META_PARQUET = EMB_DIR / "clip_meta.parquet"

def pick_col(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def infer_dim_and_model():
    feats_path = NORM_FEATS if NORM_FEATS.exists() else FEATS_NPY
    if not feats_path.exists():
        raise FileNotFoundError(f"Missing embeddings at {feats_path}")
    arr = np.load(feats_path, mmap_mode="r")
    dim = int(arr.shape[1])
    dim_to_model = {512: "ViT-B-32", 768: "ViT-L-14", 1024: "ViT-H-14"}
    return dim, dim_to_model.get(dim, "ViT-B-32")

def get_device():
    try:
        import torch_directml  # type: ignore
        return torch_directml.device()
    except Exception:
        return torch.device("cpu")

def load_openclip(model_name, device):
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained="openai")
    model.eval()
    model = model.to(device)
    return model, preprocess

def encode_image(img_path: Path, model, preprocess, device):
    img = Image.open(img_path).convert("RGB")
    x = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        feat = model.encode_image(x)
    q = feat.float().cpu().numpy()
    q /= (np.linalg.norm(q, axis=1, keepdims=True) + 1e-10)
    return q[0].astype("float32")

def search_numpy(query_vec: np.ndarray, topk: int):
    feats_path = NORM_FEATS if NORM_FEATS.exists() else FEATS_NPY
    feats = np.load(feats_path, mmap_mode="r").astype("float32")
    norms = np.linalg.norm(feats, axis=1, keepdims=True) + 1e-10
    feats = feats / norms
    sims = feats @ query_vec
    k = min(topk, sims.shape[0])
    idx = np.argpartition(-sims, range(k))[:k]
    idx = idx[np.argsort(-sims[idx])]
    return sims[idx], idx

def compose_item(brand: str, name: str, size: str):
    parts = []
    if brand: parts.append(str(brand).strip())
    if name: parts.append(str(name).strip())
    text = " ".join(parts).strip()
    if size: text = f"{text} ({str(size).strip()})"
    return text or (name or "").strip()

def main():
    ap = argparse.ArgumentParser(description="Image → Top-1 product → Cashier-ready PDF")
    ap.add_argument("--image", required=True, help="Path to query image (JPG/PNG)")
    ap.add_argument("--store", required=True, help="Retailer (e.g., Walmart)")
    ap.add_argument("--price", required=True, help="Price in CAD (e.g., 6.97)")
    ap.add_argument("--url", default="", help="Offer/product URL (optional)")
    ap.add_argument("--valid-from", default="", help="YYYY-MM-DD (optional)")
    ap.add_argument("--valid-to", default="", help="YYYY-MM-DD (optional)")
    ap.add_argument("--policy", default="", help="Key in data\\policies.json (e.g., walmart)")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--model", default="", help="Override CLIP model; blank = infer")
    ap.add_argument("--use-query-image", action="store_true", help="Force using your query photo instead of matched image")
    ap.add_argument("--open", action="store_true", help="Open the PDF after creation")
    args = ap.parse_args()

    query_img = Path(args.image)
    if not query_img.exists():
        raise FileNotFoundError(query_img)
    if not META_PARQUET.exists():
        raise FileNotFoundError(META_PARQUET)

    dim, inferred_model = infer_dim_and_model()
    model_name = args.model or inferred_model
    device = get_device()
    model, preprocess = load_openclip(model_name, device)
    q = encode_image(query_img, model, preprocess, device)

    sims, idx = search_numpy(q, args.topk)
    df = pd.read_parquet(META_PARQUET)

    col_path = pick_col(df, ["path","filepath","image_path","img_path","relpath"])
    col_name = pick_col(df, ["title","name","product_name","item"])
    col_upc  = pick_col(df, ["upc","barcode","ean"])
    col_brand= pick_col(df, ["brand","manufacturer"])
    col_size = pick_col(df, ["size","weight","variant","package_size"])

    top_i = int(idx[0])
    row = df.iloc[top_i]
    upc = str(row[col_upc]) if col_upc else ""
    name = str(row[col_name]) if col_name else ""
    brand = str(row[col_brand]) if col_brand else ""
    size = str(row[col_size]) if col_size else ""
    item_text = compose_item(brand, name, size)

    # Prefer matched catalog image; fallback to your query photo
    matched_img = None
    if col_path:
        candidate = Path(row[col_path])
        # if path in meta is relative, resolve under project root
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        if candidate.exists():
            matched_img = candidate

    chosen_img = query_img if args.use_query_image or not matched_img else matched_img

    print(f"[info] backend=numpy dim={dim} model={model_name} device={device}")
    print(f"[info] query={query_img}")
    print("=== Top-1 match ===")
    print(f"score={float(sims[0]):.4f}  upc={upc}")
    print(f"name={item_text}")
    if col_path: print(f"path={row[col_path]}")
    print(f"[info] embedding image in PDF: {chosen_img}")

    out_pdf = make_pdf(
        store=args.store,
        price=args.price,
        item=item_text if item_text else (name or "Unknown item"),
        upc=upc,
        valid_from=args.valid_from,
        valid_to=args.valid_to,
        url=args.url,
        product_image=str(chosen_img),
        policy_key=args.policy,
        cashier_note=""
    )
    print(out_pdf)

    if args.open:
        try:
            os.startfile(out_pdf)
        except Exception:
            pass

if __name__ == "__main__":
    main()
