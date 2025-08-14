# visual_scan.py
# Query product *photos* against your CLIP visual index (no barcode needed).

from pathlib import Path
import json
import numpy as np
import pandas as pd
from PIL import Image

# ---- Paths your builder uses ----
EMB_DIR = Path("embeddings")
VEC_NPY = EMB_DIR / "clip_vectors.npy"       # (N, 512) float32, L2-normalized
META_PQ = EMB_DIR / "clip_meta.parquet"      # rows aligned with vectors

def _pick_device():
    """
    Pick the best device available:
    - DirectML (AMD/NVIDIA via torch-directml) if available -> 'privateuseone:0'
    - else CPU
    """
    try:
        import torch_directml, torch
        dml = torch_directml.device()
        # quick allocation to be sure it works
        _ = torch.randn(1, 3, 224, 224, device=dml)
        return ("dml", dml)
    except Exception:
        pass

    # CPU fallback
    return ("cpu", None)

def _load_clip(device_hint="auto"):
    """
    Load OpenCLIP ViT-B/32 + preprocess. Sends tensors to the chosen device.
    """
    import torch, open_clip

    if device_hint == "auto":
        kind, dev = _pick_device()
    elif device_hint == "dml":
        # force DirectML if possible
        import torch_directml
        dev = torch_directml.device()
        kind = "dml"
    else:
        kind, dev = "cpu", None

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    model.eval()

    # Move model to device
    if kind == "dml":
        # torch-directml uses .to(dml_device)
        model = model.to(dev)
        return model, preprocess, ("dml", dev)
    else:
        return model, preprocess, ("cpu", None)

def _load_index():
    """
    Load vectors and metadata. We’ll do brute-force cosine sim with NumPy (fast enough).
    """
    if not VEC_NPY.exists() or not META_PQ.exists():
        raise RuntimeError(
            "Missing embeddings. Run your builder first to create:\n"
            f"  {VEC_NPY}\n  {META_PQ}"
        )
    vecs = np.load(VEC_NPY).astype("float32")   # (N,512), expected normalized
    meta = pd.read_parquet(META_PQ)
    if len(meta) != vecs.shape[0]:
        raise RuntimeError(f"Rows mismatch: meta={len(meta)} vs vecs={vecs.shape[0]}")
    return vecs, meta

def _embed_image(model, preprocess, dev_info, image_path: str) -> np.ndarray:
    """
    Encode a single image to a 512-D normalized vector.
    """
    import torch

    img = Image.open(image_path).convert("RGB")
    t = preprocess(img).unsqueeze(0)  # (1,3,224,224)

    kind, dev = dev_info
    if kind == "dml":
        t = t.to(dev)
        with torch.no_grad():
            f = model.encode_image(t)
    else:
        with torch.no_grad():
            f = model.encode_image(t)

    f = f / f.norm(dim=-1, keepdim=True)
    return f[0].detach().cpu().numpy().astype("float32")  # (512,)

def match_image(image_path: str, topk: int = 5, device="auto"):
    """
    Returns a list of top-K matches: rank, score, barcode, product_name, local image_path.
    """
    model, preprocess, dev_info = _load_clip(device)
    vecs, meta = _load_index()
    q = _embed_image(model, preprocess, dev_info, image_path)  # (512,)

    # cosine similarity since both are L2-normalized -> dot product
    sims = vecs @ q  # (N,)
    if topk > len(sims):
        topk = len(sims)
    idx = np.argpartition(-sims, topk-1)[:topk]
    idx = idx[np.argsort(-sims[idx])]

    results = []
    for rank, i in enumerate(idx, 1):
        row = meta.iloc[int(i)]
        results.append({
            "rank": rank,
            "score": float(sims[i]),
            "barcode": str(row.get("barcode", "")),
            "product_name": str(row.get("product_name", "")),
            "image_path": str(row.get("image_path", "")),
        })
    return results

if __name__ == "__main__":
    # quick manual test:
    p = input("Path to a product photo: ").strip('"').strip()
    if not p:
        print("No image provided."); raise SystemExit
    out = match_image(p, topk=5, device="auto")
    if not out:
        print("No matches.")
    else:
        for r in out:
            print(f"{r['rank']}) {r['score']:.3f} [{r['barcode']}] {r['product_name']}")
