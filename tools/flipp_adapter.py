import re
from typing import Any

def _norm(query: Any) -> str:
    """
    Coerce any query (str, dict, list/tuple) into a simple string.
    - dict: join string-like values ("name", "product", "label", etc.)
    - list/tuple: join items
    - fallback: str(query)
    Then collapse whitespace.
    """
    def _is_strish(x):
        return isinstance(x, str) and x.strip() != ""

    if isinstance(query, str):
        text = query
    elif isinstance(query, dict):
        # collect common keys first, then add any other stringy values
        keys = ["name", "product", "title", "label", "brand", "size", "variant"]
        parts = []
        for k in keys:
            v = query.get(k)
            if _is_strish(v):
                parts.append(v.strip())
        # include any other string values we didn't cover
        for k, v in query.items():
            if k in keys:
                continue
            if _is_strish(v):
                parts.append(v.strip())
        text = " ".join(parts) if parts else str(query)
    elif isinstance(query, (list, tuple)):
        parts = [str(x).strip() for x in query if str(x).strip()]
        text = " ".join(parts)
    else:
        text = str(query)

    # collapse whitespace
    return re.sub(r"\s+", " ", text).strip()
