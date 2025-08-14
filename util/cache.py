# util/cache.py
import os, json, hashlib, time
from typing import Optional, Any, Dict

DEFAULT_DIR = r"F:\Docs\off_data\cache\flipp"
DEFAULT_TTL_SECONDS = 24 * 3600  # 24 hours

def _key_to_path(base_dir: str, key: str) -> str:
    os.makedirs(base_dir, exist_ok=True)
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(base_dir, f"{h}.json")

def load_json(key: str, base_dir: str = DEFAULT_DIR, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Optional[Dict[str, Any]]:
    path = _key_to_path(base_dir, key)
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        if time.time() - mtime > ttl_seconds:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_json(key: str, data: Dict[str, Any], base_dir: str = DEFAULT_DIR) -> None:
    path = _key_to_path(base_dir, key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
