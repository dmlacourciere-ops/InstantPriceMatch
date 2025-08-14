# providers/scraper.py
# OFF dump -> Canada filter -> CSV batches under F:\Docs\off_data\runs\<timestamp>\...
# Mirrors finished CSV + manifest to F:\Docs\off_data\latest\
# Robust Canada detection + reuse of already-downloaded JSONL.

import os
import json
import time
import gzip
import shutil
import pandas as pd
from shutil import disk_usage
from typing import List, Dict, Optional
from datetime import datetime

# --- optional progress bar (won't crash if tqdm missing) ---
try:
    from tqdm import tqdm  # type: ignore
    def progress_iter(iterable, **kwargs):
        return tqdm(iterable, **kwargs)
except Exception:
    def progress_iter(iterable, **kwargs):
        return iterable

# --- optional CPU monitoring (gentle throttle) ---
try:
    import psutil  # type: ignore
except Exception:
    psutil = None

# ================== CONFIG ==================
DEFAULT_BASE_DIR = os.environ.get("OFF_BASE_DIR", r"F:\Docs")
DEFAULT_BATCH_SIZE = 5000
DEFAULT_MIN_FREE_GB = 20

# Parsing throttle: aim to keep CPU <= ~85%
CPU_TARGET_MAX = 85
CPU_CHECK_EVERY = 1000
CPU_BACKOFF_SLEEP = 0.10

SCHEMA = [
    "barcode","product_name","brand","quantity","packaging",
    "categories","labels","ingredients_text","serving_size",
    "nutrition_grade","image_url","last_updated_t","source"
]
# ============================================

def _paths(base_dir: str) -> Dict[str, str]:
    root = os.path.join(base_dir, "off_data")
    runs_root = os.path.join(root, "runs")
    latest_root = os.path.join(root, "latest")
    # cache folder holds the JSONL you already have (so we don't re-download)
    cache_root = os.path.join(root, "cache")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(runs_root, stamp)
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(latest_root, exist_ok=True)
    os.makedirs(cache_root, exist_ok=True)
    return {
        "root": root,
        "runs_root": runs_root,
        "latest_root": latest_root,
        "cache_root": cache_root,
        "run_dir": run_dir,
        "cache_jsonl": os.path.join(cache_root, "products.jsonl"),
        "out_csv": os.path.join(run_dir, "off_canada_products.csv"),
        "latest_csv": os.path.join(latest_root, "off_canada_products.csv"),
        "run_manifest": os.path.join(run_dir, "manifest.json"),
        "latest_manifest": os.path.join(latest_root, "manifest.json"),
    }

def _free_gb(path: str) -> float:
    total, used, free = disk_usage(path)
    return free / (1024 ** 3)

def _cpu_throttle(line_idx: int) -> None:
    if psutil is None or line_idx % CPU_CHECK_EVERY != 0:
        return
    try:
        usage = psutil.cpu_percent(interval=0.05)
        if usage >= CPU_TARGET_MAX:
            over = min(usage - CPU_TARGET_MAX, 50)
            time.sleep(CPU_BACKOFF_SLEEP * (1 + (over / 25.0)))
    except Exception:
        pass

def _is_canadian(prod: Dict) -> bool:
    """
    True if the product is tagged/says it's in Canada.
    OFF uses 'countries_tags': ['en:canada','fr:canada',...] and/or 'countries'/'countries_hierarchy'.
    """
    # tags like 'en:canada', 'fr:canada'
    tags = [str(t).lower().strip() for t in (prod.get("countries_tags") or [])]
    if any(t.endswith(":canada") or t == "canada" for t in tags):
        return True
    # free-text string
    cstr = (prod.get("countries") or "").lower()
    if "canada" in cstr:
        return True
    # hierarchy sometimes present
    hier = [str(h).lower().strip() for h in (prod.get("countries_hierarchy") or [])]
    if any(h.endswith(":canada") or h == "canada" for h in hier):
        return True
    return False

def _write_manifest(path: str, data: Dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _find_latest_file_under(root: str, filename: str) -> Optional[str]:
    """Find newest runs/*/filename path."""
    if not os.path.isdir(root):
        return None
    newest = None; newest_mtime = -1.0
    for entry in os.scandir(root):
        if entry.is_dir():
            p = os.path.join(entry.path, filename)
            if os.path.isfile(p):
                mt = os.path.getmtime(p)
                if mt > newest_mtime:
                    newest_mtime = mt
                    newest = p
    return newest

def scrape_and_save(
    base_dir: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    min_free_gb: int = DEFAULT_MIN_FREE_GB,
) -> None:
    """
    Parse the already-downloaded OFF JSONL (we'll reuse your last run's file),
    filter to Canada, write CSV in a new timestamped run dir, and mirror to latest/.
    """
    base_dir = base_dir or DEFAULT_BASE_DIR
    p = _paths(base_dir)

    if _free_gb(base_dir) < min_free_gb:
        print(f"[abort] Not enough free space in {base_dir}. Need >= {min_free_gb} GB free.")
        return

    # --- Reuse your downloaded JSONL ---
    if not os.path.exists(p["cache_jsonl"]):
        # find the newest products.jsonl from your previous runs and copy it into cache
        prev_jsonl = _find_latest_file_under(os.path.join(p["root"], "runs"), "products.jsonl")
        if not prev_jsonl:
            print("[error] Could not find a previously extracted products.jsonl in runs/. "
                  "Run your old build once to download+extract, or tell me and I'll re-enable download here.")
            return
        print(f"[reuse] using existing JSONL: {prev_jsonl}")
        shutil.copy2(prev_jsonl, p["cache_jsonl"])
    else:
        print(f"[reuse] using cached JSONL: {p['cache_jsonl']}")

    # --- Parse + save (Canada only) ---
    print(f"[parse] reading: {p['cache_jsonl']}")
    start = time.time()
    batch: List[Dict] = []
    saved = 0
    header_written = os.path.exists(p["out_csv"])
    seen_lines = 0
    matched_canada = 0

    try:
        with open(p["cache_jsonl"], "r", encoding="utf-8") as f:
            for line in progress_iter(f, unit=" lines"):
                seen_lines += 1
                if _free_gb(base_dir) < min_free_gb:
                    print(f"[stop] free space < {min_free_gb} GB, stopping safely.")
                    break
                _cpu_throttle(seen_lines)

                try:
                    prod = json.loads(line)
                except Exception:
                    continue

                if not _is_canadian(prod):
                    continue
                matched_canada += 1

                row = {
                    "barcode": prod.get("code", ""),
                    "product_name": prod.get("product_name", ""),
                    "brand": prod.get("brands", ""),
                    "quantity": prod.get("quantity", ""),
                    "packaging": prod.get("packaging", ""),
                    "categories": prod.get("categories", ""),
                    "labels": prod.get("labels", ""),
                    "ingredients_text": prod.get("ingredients_text", ""),
                    "serving_size": prod.get("serving_size", ""),
                    "nutrition_grade": prod.get("nutrition_grades", ""),
                    "image_url": prod.get("image_front_url", ""),
                    "last_updated_t": prod.get("last_modified_t", 0),
                    "source": "OpenFoodFacts dump",
                }
                batch.append(row)

                if len(batch) >= batch_size:
                    header_written = _append_csv(batch, p["out_csv"], header_written)
                    saved += len(batch)
                    print(f"[save] total saved so far: {saved:,} (matched {matched_canada:,} / seen {seen_lines:,})")
                    batch.clear()

        if batch:
            header_written = _append_csv(batch, p["out_csv"], header_written)
            saved += len(batch)

    except KeyboardInterrupt:
        print("\n[stop] You pressed Ctrl+C — partial data saved. You can resume later.")

    dur = time.time() - start

    manifest = {
        "run_dir": p["run_dir"],
        "latest_csv": p["latest_csv"],
        "rows_written": saved,
        "matched_canada": matched_canada,
        "lines_seen": seen_lines,
        "country_filter": "en/fr tags + countries string + hierarchy",
        "schema": SCHEMA,
        "source_jsonl": p["cache_jsonl"],
        "started_at": datetime.fromtimestamp(start).isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "duration_minutes": round(dur/60, 2),
        "cpu_target_max_percent": CPU_TARGET_MAX,
        "batch_size": batch_size,
        "min_free_gb": min_free_gb,
        "base_dir": base_dir,
    }
    _write_manifest(p["run_manifest"], manifest)

    # update latest only if we actually wrote rows
    if saved > 0 and os.path.exists(p["out_csv"]):
        try:
            shutil.copy2(p["out_csv"], p["latest_csv"])
            shutil.copy2(p["run_manifest"], p["latest_manifest"])
            print(f"[latest] updated: {p['latest_csv']}")
        except Exception as e:
            print(f"[warn] failed to update latest: {e}")
    else:
        print("[info] No Canadian rows saved this run; skipping latest/ update.")

    print(f"[done] wrote {saved:,} Canadian products to: {p['out_csv']}")
    print(f"[time] {dur/60:.1f} min")

def _append_csv(rows: List[Dict], out_csv: str, header_written: bool) -> bool:
    if not rows: return header_written
    df = pd.DataFrame(rows, columns=SCHEMA)
    mode = "a" if os.path.exists(out_csv) or header_written else "w"
    df.to_csv(out_csv, mode=mode, header=(mode == "w"), index=False)
    return True
