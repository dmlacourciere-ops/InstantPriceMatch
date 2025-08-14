# tools/build_sklearn_index.py
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
import joblib

EMB_DIR = Path("embeddings")
FEATS_NPY = EMB_DIR / "clip_feats.npy"          # produced by build_visual_index.py --mode embed
META_PARQ = EMB_DIR / "clip_meta.parquet"       # rows meta (barcode, name, image_path, etc.)
OUT_INDEX = EMB_DIR / "knn_cosine.joblib"

def main():
    if not FEATS_NPY.exists() or not META_PARQ.exists():
        raise SystemExit(
            f"[error] Missing embeddings.\n"
            f"  need: {FEATS_NPY}\n"
            f"  need: {META_PARQ}\n"
            f"Run:  python build_visual_index.py --mode embed --device dml"
        )

    feats = np.load(FEATS_NPY).astype("float32")
    # normalize to unit length for cosine distance
    norms = np.linalg.norm(feats, axis=1, keepdims=True) + 1e-9
    feats = feats / norms

    print(f"[info] fitting KNN on {feats.shape[0]} vectors (512-d)…")
    knn = NearestNeighbors(metric="cosine", n_neighbors=50, algorithm="auto", n_jobs=-1)
    knn.fit(feats)

    OUT_INDEX.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(knn, OUT_INDEX)
    print(f"[done] wrote: {OUT_INDEX}")

if __name__ == "__main__":
    main()
