import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
import torch

ROOT = Path(__file__).resolve().parents[1]
EMB_DIR = ROOT / "embeddings"
FEATS_NPY = EMB_DIR / "clip_feats.npy"
NORM_FEATS = EMB_DIR / "clip_feats_norm.npy"
FAISS_IDX = EMB_DIR / "faiss.index"
META_PARQUET = EMB_DIR / "clip_meta.parquet"

def get_device(pref: str = "auto"):
    if pref.lower() == "cpu":
        return torch.device("cpu")
    try:
        import torch_directml  # type: ignore
        if pref.lower() in ("auto", "dml"):
            return torch_directml.device()
    except Exception:
        pass
    if torch.cuda.is_available() and pref.lower() in ("auto", "cuda"):
        return torch.device("cuda")
    return torch.device("cpu")

def load_openclip(model_name="ViT-B-32", device=None):
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained="openai")
    model.eval()
    if device is not None:
        model = model.to(device)
    return model, preprocess

def encode_image(path: Path, model, preprocess, device):
    img = Image.open(path).convert("RGB")
    x = preprocess(img).unsqueeze(0)
    if str(device) == "privateuseone" or device.__class__.__name__ == "DirectMLDevice":
        # DirectML device
        x = x.to(device)
        with torch.no_grad():
            feat = model.encode_image(x)
        feat = feat.detach().cpu().numpy().astype("float32")
    else:
        x = x.to(device)
        with torch.no_grad():
            feat = model.encode_image(x)
        feat = feat.float().cpu().numpy()
    # L2 normalize
    feat /= (np.linalg.norm(feat, axis=1, keepdims=True) + 1e-10)
    return feat[0]

def search_faiss(query_vec: np.ndarray, topk: int):
    import faiss
    if not FAISS_IDX.exists():
        raise FileNotFoundError("FAISS index not found.")
    index = faiss.read_index(str(FAISS_IDX))
    D, I = index.search(query_vec.astype("float32")[None, :], topk)
    return D[0], I[0]

def search_numpy(query_vec: np.ndarray, topk: int):
    feats_path = NORM_FEATS if NORM_FEATS.exists() else FEATS_NPY
    feats = np.load(feats_path)
    # Ensure normalized
    if feats.ndim != 2:
        raise ValueError(f"Bad feature shape: {feats.shape}")
    norms = np.linalg.norm(feats, axis=1, keepdims=True) + 1e-10
    feats = feats.astype("float32", copy=False) / norms
    sims = feats @ query_vec.astype("float32")
    # topk via argpartition
    idx = np.argpartition(-sims, range(min(topk, sims.shape[0])))[:topk]
    idx = idx[np.argsort(-sims[idx])]
    return sims[idx], idx

def pick_col(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def main():
    ap = argparse.ArgumentParser(description="Search CLIP visual matches over precomputed embeddings.")
    ap.add_argument("--image", required=True, help="Path to query image")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "dml"])
    ap.add_argument("--model", default="ViT-B-32", help="CLIP model used when building the embeddings")
    args = ap.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        raise FileNotFoundError(image_path)

    device = get_device(args.device)
    model, preprocess = load_openclip(args.model, device=device)
    q = encode_image(image_path, model, preprocess, device)

    # Try FAISS first, then NumPy fallback
    used = "faiss"
    try:
        sims, idx = search_faiss(q, args.topk)
    except Exception:
        used = "numpy"
        sims, idx = search_numpy(q, args.topk)

    meta_path = META_PARQUET
    if not meta_path.exists():
        raise FileNotFoundError(meta_path)
    df = pd.read_parquet(meta_path)

    col_path = pick_col(df, ["path", "filepath", "image_path", "img_path"])
    col_name = pick_col(df, ["title", "name", "product_name", "item"])
    col_upc = pick_col(df, ["upc", "barcode", "ean"])
    col_brand = pick_col(df, ["brand", "manufacturer"])
    col_size = pick_col(df, ["size", "weight", "variant"])

    print(f"[info] backend={used} device={device} model={args.model}")
    print(f"[info] query: {image_path}")
    print("=== Top matches ===")
    for rank, (i, s) in enumerate(zip(idx, sims), start=1):
        row = df.iloc[int(i)]
        name = row[col_name] if col_name else ""
        upc = row[col_upc] if col_upc else ""
        brand = row[col_brand] if col_brand else ""
        size = row[col_size] if col_size else ""
        path = row[col_path] if col_path else ""
        print(f"{rank:>2}. score={s:.4f}  upc={upc}  brand={brand}  size={size}")
        print(f"    name={name}")
        print(f"    path={path}")

if __name__ == "__main__":
    main()
