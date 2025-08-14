# test_query.py — quick smoke test for the built index (no new embeddings needed)
from pathlib import Path
import json, sys
import numpy as np, pandas as pd, joblib

idx = Path("index")
vecs = np.load(idx / "vectors_norm.npy")
if vecs.size == 0:
    print("No vectors found."); sys.exit(1)

meta = pd.read_parquet(idx / "clip_meta.parquet")
nn   = joblib.load(idx / "nn.pkl")

# use the first vector as a query (just to validate nearest-neighbor works)
q = vecs[0:1]
dists, inds = nn.kneighbors(q, n_neighbors=min(5, len(vecs)))
inds = inds[0].tolist()
dists = dists[0].tolist()
sims  = [1 - d for d in dists]  # cosine similarity

rows = meta.iloc[inds].to_dict(orient="records")
out  = [{"rank": i+1, "index": idx, "cosine_similarity": round(sim, 6), "row": row}
        for i, (idx, sim, row) in enumerate(zip(inds, sims, rows))]
print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
