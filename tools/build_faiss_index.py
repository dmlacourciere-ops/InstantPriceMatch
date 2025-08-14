import argparse
from pathlib import Path
from datetime import datetime
import json
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EMB_DIR = ROOT / "embeddings"
FEATS_NPY = EMB_DIR / "clip_feats.npy"
FAISS_IDX = EMB_DIR / "faiss.index"
META_JSON = EMB_DIR / "faiss.meta.json"
NORM_FEATS = EMB_DIR / "clip_feats_norm.npy"

def l2_normalize(x: np.ndarray) -> np.ndarray:
    x = x.astype("float32", copy=False)
    n = np.linalg.norm(x, axis=1, keepdims=True) + 1e-10
    x /= n
    return x

def build_faiss(feats: np.ndarray, out_path: Path):
    import faiss  # may not exist; caller ensures before calling
    d = feats.shape[1]
    faiss.normalize_L2(feats)
    index = faiss.IndexFlatIP(d)
    index.add(feats)
    faiss.write_index(index, str(out_path))

def main():
    ap = argparse.ArgumentParser(description="Build FAISS index (with fallback artifacts).")
    ap.add_argument("--feats", default=str(FEATS_NPY), help="Path to clip_feats.npy")
    ap.add_argument("--out", default=str(FAISS_IDX), help="Path to write faiss.index")
    ap.add_argument("--force", action="store_true", help="Overwrite existing index")
    args = ap.parse_args()

    feats_path = Path(args.feats)
    out_path = Path(args.out)
    EMB_DIR.mkdir(parents=True, exist_ok=True)

    if not feats_path.exists():
        raise FileNotFoundError(f"Missing embeddings: {feats_path}")

    feats = np.load(feats_path)
    if feats.ndim != 2:
        raise ValueError(f"Expected 2D features, got {feats.shape}")

    feats = l2_normalize(feats.copy())

    # Always save normalized features for the NumPy fallback
    np.save(NORM_FEATS, feats)

    # Try FAISS if installed
    built = False
    try:
        import faiss  # noqa
        if out_path.exists() and not args.force:
            print(f"[info] {out_path.name} exists. Use --force to rebuild.")
        else:
            build_faiss(feats, out_path)
            built = True
    except Exception as e:
        print(f"[warn] FAISS not available or failed to build: {e}")
        print("[warn] You can still search via the NumPy fallback.")

    META_JSON.write_text(json.dumps({
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "dim": int(feats.shape[1]),
        "num_items": int(feats.shape[0]),
        "normalized": True,
        "faiss_index": str(out_path.relative_to(ROOT)) if out_path.exists() else "",
        "numpy_fallback": str(NORM_FEATS.relative_to(ROOT))
    }, indent=2), encoding="utf-8")

    print(f"[done] Features: {feats.shape}. "
          f"FAISS: {'OK' if built and out_path.exists() else 'skipped'}. "
          f"Fallback saved: {NORM_FEATS.name}")

if __name__ == "__main__":
    main()
