# history.py
import os, json, uuid, datetime, webbrowser
from typing import Dict, Any, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
HISTORY_FILE = os.path.join(DATA_DIR, "history.jsonl")

os.makedirs(DATA_DIR, exist_ok=True)

def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")

def log_proof(entry: Dict[str, Any]) -> None:
    """Append a proof record to history.jsonl"""
    e = dict(entry)
    e.setdefault("id", str(uuid.uuid4()))
    e.setdefault("ts", _now_iso())
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")

def _read_all() -> List[Dict[str, Any]]:
    if not os.path.exists(HISTORY_FILE):
        return []
    out: List[Dict[str, Any]] = []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out

def list_recent(n: int = 50) -> List[Dict[str, Any]]:
    rows = _read_all()
    rows.sort(key=lambda r: r.get("ts",""), reverse=True)
    return rows[:n]

def open_image(path: str) -> None:
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open(f"file://{path}")
    except Exception:
        pass
