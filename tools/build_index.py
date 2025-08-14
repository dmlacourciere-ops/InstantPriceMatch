from pathlib import Path
import numpy as np
import pandas as pd
from tqdm import tqdm
from PIL import Image
import joblib

# --------- config
IMAGES_DIR = Path("images")
EMB_DIR    = Path("embeddings")
MODEL_NAME = "ViT-B-32"
PRETRAINED = "laion2b_s34b_b79k"
BATCH      = 32

def load_clip():
    import torch, open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(MODEL_NAME, pretrained=PRETRAINED)
    model.eval()
    return model, preprocess

def find_images():
    exts = (".jpg", ".jpeg", ".png", ".webp")
    return [p for p in IMAGES_DIR.rglob("*") if p.suffix.lower() in exts]

def embed_batch(model, preprocess, batch):
    import torch
    imgs = []
    metas = []
    for p in batch:
        try:
            img = Image.open(p).convert("RGB")
            t = preprocess(img)
            imgs.append(t)
            # pull barcode from filename or directory if you encoded it there; else blank
            metas.append({"image_path": str(p)})
        except Exception:
            pass
    if not imgs:
        return None, []
    with torch.no_grad():
        x = torch.stack(imgs, 0)
        feats = model.encode_image(x)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        feats = feats.cpu().numpy().astype("float32")
    return feats, metas

def main():
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    model, preprocess = load_clip()

    imgs = find_images()
    if not imgs:
        print("[error] no images under ./images — did the downloader run?")
        return

    all_vecs = []
    all_meta = []
    for i in tqdm(range(0, len(imgs), BATCH), desc="embed"):
        feats, metas = embed_batch(model, preprocess, imgs[i:i+BATCH])
        if feats is None:
            continue
        all_vecs.append(feats)
        all_meta.extend(metas)

    if not all_meta:
        print("[error] nothing embedded.")
        return

    vecs = np.concatenate(all_vecs, axis=0)
    meta = pd.DataFrame(all_meta)
    print(f"[ok] embeddings: {vecs.shape}  rows: {len(meta):,}")

    np.save(EMB_DIR / "clip_vectors.npy", vecs)
    meta.to_parquet(EMB_DIR / "clip_meta.parquet", index=False)

    # ---- build KNN (cosine)
    from sklearn.neighbors import NearestNeighbors
    knn = NearestNeighbors(metric="cosine", algorithm="auto", n_neighbors=50, n_jobs=-1)
    knn.fit(vecs)
    joblib.dump(knn, EMB_DIR / "knn_index.joblib")

    print("[done] wrote:")
    print("  -", EMB_DIR / "clip_vectors.npy")
    print("  -", EMB_DIR / "clip_meta.parquet")
    print("  -", EMB_DIR / "knn_index.joblib")

if __name__ == "__main__":
    main()
