# rebuild_off_csv_with_images.py
import os, json, time, shutil
from typing import Optional, Dict, Any
import pandas as pd
from tqdm import tqdm

# ---- paths (adjust base only if you changed it) ----
BASE = r"F:\Docs\off_data"
CACHE_JSONL = os.path.join(BASE, "cache", "products.jsonl")
RUNS_DIR    = os.path.join(BASE, "runs")
LATEST_DIR  = os.path.join(BASE, "latest")
os.makedirs(RUNS_DIR, exist_ok=True)
os.makedirs(LATEST_DIR, exist_ok=True)

ts = time.strftime("%Y%m%d_%H%M%S")
OUT_CSV   = os.path.join(RUNS_DIR, ts, "off_canada_products.csv")
LATEST_CSV = os.path.join(LATEST_DIR, "off_canada_products.csv")
os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)

BATCH_SIZE = 25_000  # write in chunks to keep RAM low

def _is_canada(prod: Dict[str, Any]) -> bool:
    # Countries can appear in several places
    tags = [str(x).lower() for x in prod.get("countries_tags", [])]
    if "en:canada" in tags or "fr:canada" in tags:
        return True
    countries = str(prod.get("countries", "")).lower()
    return "canada" in countries

def _name_of(prod: Dict[str, Any]) -> str:
    # Prefer English name, then French, then generic, then fallback
    for k in ("product_name_en", "product_name", "product_name_fr",
              "generic_name_en", "generic_name", "generic_name_fr"):
        v = str(prod.get(k, "")).strip()
        if v:
            return v
    return ""

def _choose_image(prod: Dict[str, Any]) -> Optional[str]:
    """
    Try very hard to extract a usable front image URL.
    OFF may store it under:
      - selected_images.front.display.{en,fr}
      - images.front_{en,fr}.display.{en,fr}
      - image_front_url / image_url / image_small_url / image_thumb_url
    """
    # 1) selected_images
    si = prod.get("selected_images") or {}
    if isinstance(si, dict):
        front = si.get("front") or {}
        if isinstance(front, dict):
            display = front.get("display") or {}
            if isinstance(display, dict):
                for lang in ("en", "fr"):
                    url = display.get(lang)
                    if isinstance(url, str) and url.startswith("http"):
                        return url
            # fallback to small/thumb if display missing
            for bucket in ("small", "thumb"):
                d = front.get(bucket) or {}
                if isinstance(d, dict):
                    for lang in ("en", "fr"):
                        url = d.get(lang)
                        if isinstance(url, str) and url.startswith("http"):
                            return url

    # 2) images dict
    imgs = prod.get("images") or {}
    if isinstance(imgs, dict):
        for key in ("front_en", "front_fr", "front"):
            node = imgs.get(key)
            if isinstance(node, dict):
                display = node.get("display") or {}
                if isinstance(display, dict):
                    for lang in ("en", "fr"):
                        url = display.get(lang)
                        if isinstance(url, str) and url.startswith("http"):
                            return url

    # 3) direct keys
    for k in ("image_front_url", "image_url", "image_small_url", "image_thumb_url"):
        url = prod.get(k)
        if isinstance(url, str) and url.startswith("http"):
            return url

    # 4) last-ditch: try building a canonical path (often works)
    code = str(prod.get("code", "")).strip()
    if code.isdigit():
        p = "/".join([code[:3], code[3:6], code[6:9], code[9:]]) if len(code) > 9 else code
        # Try common file names in order
        candidates = [
            f"https://images.openfoodfacts.org/images/products/{p}/front_en.400.jpg",
            f"https://images.openfoodfacts.org/images/products/{p}/front.400.jpg",
            f"https://images.openfoodfacts.org/images/products/{p}/1.400.jpg",
        ]
        # We won’t HEAD each URL (too slow at scale); return first candidate.
        return candidates[0]

    return None

def main() -> None:
    src = CACHE_JSONL
    if not os.path.exists(src):
        print(f"[error] JSONL not found: {src}")
        return

    print(f"[use] {src}")
    print(f"[parse] reading: {src}")

    rows = []
    saved_total = 0
    with_img = 0
    header_written = False

    def flush():
        nonlocal rows, saved_total, header_written
        if not rows:
            return
        df = pd.DataFrame(rows)
        df = df.drop_duplicates(subset=["barcode"])
        mode = "a" if header_written else "w"
        df.to_csv(OUT_CSV, index=False, header=not header_written, mode=mode, encoding="utf-8")
        saved_total += len(df)
        header_written = True
        rows.clear()
        print(f"[save] total rows written so far: {saved_total:,} (with images: {with_img:,})")

    with open(src, "r", encoding="utf-8") as f:
        for line in tqdm(f, unit="lines"):
            try:
                prod = json.loads(line)
            except Exception:
                continue

            if not _is_canada(prod):
                continue

            code = str(prod.get("code", "")).strip()
            if not code:
                continue

            img = _choose_image(prod)
            if not img:
                # skip rows without any usable image
                continue
            with_img += 1

            rows.append({
                "barcode": code,
                "product_name": _name_of(prod),
                "brand": (prod.get("brands") or "").strip(),
                "quantity": (prod.get("quantity") or "").strip(),
                "packaging": (prod.get("packaging") or "").strip(),
                "categories": (prod.get("categories") or "").strip(),
                "labels": (prod.get("labels") or "").strip(),
                "ingredients_text": (prod.get("ingredients_text") or "").strip(),
                "serving_size": (prod.get("serving_size") or "").strip(),
                "nutrition_grade": prod.get("nutrition_grade_fr") or prod.get("nutrition_grade"),
                "image_url": img,
                "last_updated_t": prod.get("last_modified_t", 0),
                "source": "OFF dump (w/images)"
            })

            if len(rows) >= BATCH_SIZE:
                flush()

    flush()

    print(f"[done] wrote {saved_total:,} rows to: {OUT_CSV}")
    print(f"[info] rows with image_url present: {with_img:,}")

    try:
        shutil.copy2(OUT_CSV, LATEST_CSV)
        print(f"[latest] updated: {LATEST_CSV}")
    except Exception as e:
        print("[warn] failed to update latest:", e)

if __name__ == "__main__":
    main()
