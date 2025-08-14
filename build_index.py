# build_index.py (scikit-learn, no compiler needed)
from __future__ import annotations
from pathlib import Path
import argparse, json, sys
import numpy as np, pandas as pd
try:
    from sklearn.neighbors import NearestNeighbors
    import joblib
except Exception as e:
    print("Missing deps. Install with: pip install scikit-learn joblib", file=sys.stderr); raise

def guess_emb_dir(base: Path) -> Path | None:
    for p in [base/"embeds", base/"embed", base/"embeddings", base]:
        for q in p.rglob("clip_vectors.npy"): return q.parent
    return None

def load_embeddings(emb_dir: Path):
    vp, mp = emb_dir/"clip_vectors.npy", emb_dir/"clip_meta.parquet"
    if not vp.exists(): raise FileNotFoundError(vp)
    if not mp.exists(): raise FileNotFoundError(mp)
    vecs = np.load(vp); meta = pd.read_parquet(mp)
    if vecs.ndim != 2: raise ValueError(f"Expected 2D vectors, got {vecs.shape}")
    if len(meta) != vecs.shape[0]: print(f"[warn] meta rows {len(meta)} != vectors {vecs.shape[0]}")
    return vecs, meta

def normalize_rows(X: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(X, axis=1, keepdims=True); n[n==0]=1.0; return X/n

def main():
    ap = argparse.ArgumentParser(description="Build cosine index from CLIP embeddings (sklearn)")
    ap.add_argument("--emb-dir", type=str, default=None)
    ap.add_argument("--out-dir", type=str, default="index")
    ap.add_argument("--trees", type=int, default=32, help="ignored (compat only)")
    ap.add_argument("--n_neighbors", type=int, default=50)
    args = ap.parse_args()

    base = Path(".").resolve()
    emb_dir = Path(args.emb_dir).resolve() if args.emb_dir else guess_emb_dir(base)
    if not emb_dir:
        print("[index] Could not locate clip_vectors.npy. Use --emb-dir PATH.", file=sys.stderr); sys.exit(1)

    out = Path(args.out_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    print(f"[index] Loading embeddings from: {emb_dir}")
    vecs, meta = load_embeddings(emb_dir); n, d = vecs.shape
    if n == 0: print("[index] No vectors to index.", file=sys.stderr); sys.exit(1)

    print(f"[index] Normalizing vectors: n={n} dim={d}")
    vecs_norm = normalize_rows(vecs); np.save(out/"vectors_norm.npy", vecs_norm)
    print("[index] Fitting NearestNeighbors (brute, cosine)")
    nn = NearestNeighbors(n_neighbors=min(args.n_neighbors, max(1,n)), algorithm="brute", metric="cosine", n_jobs=-1)
    nn.fit(vecs_norm); import joblib as jb; jb.dump(nn, out/"nn.pkl")
    meta.to_parquet(out/"clip_meta.parquet", index=False)
    info = {"n_items":int(n), "dim":int(d), "model":"sklearn.neighbors.NearestNeighbors",
            "metric":"cosine","algorithm":"brute","emb_dir":str(emb_dir)}
    (out/"info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print("[index] DONE"); print("Files written:"); print(f"  {out/'nn.pkl'}"); print(f"  {out/'vectors_norm.npy'}"); print(f"  {out/'clip_meta.parquet'}"); print(f"  {out/'info.json'}")

if __name__ == "__main__": main()
