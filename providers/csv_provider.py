import os
import glob
import pandas as pd
from dateutil import parser
from typing import Optional, Dict, Any, List

class CSVPriceProvider:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._cache: List[pd.DataFrame] = []
        self._load_all()

    def _load_all(self) -> None:
        pattern = os.path.join(self.data_dir, "*.csv")
        files = glob.glob(pattern)
        frames = []
        for f in files:
            try:
                df = pd.read_csv(f, dtype={"barcode": str})
                required_cols = {"barcode","product_name","price_cad","url","last_updated","retailer"}
                if not required_cols.issubset(set(df.columns)):
                    print(f"[WARN] Skipping {f} (missing required columns).")
                    continue
                df["barcode"] = df["barcode"].str.strip()
                df["price_cad"] = pd.to_numeric(df["price_cad"], errors="coerce")
                df["last_updated"] = df["last_updated"].apply(self._safe_date)
                frames.append(df)
            except Exception as e:
                print(f"[WARN] Failed to read {f}: {e}")
        if frames:
            self._cache = [pd.concat(frames, ignore_index=True)]
        else:
            self._cache = []

    @staticmethod
    def _safe_date(x):
        try:
            return parser.parse(str(x)).date()
        except Exception:
            return None

    def find_prices(self, barcode: str) -> List[Dict[str, Any]]:
        if not self._cache:
            return []
        df = self._cache[0]
        sub = df[df["barcode"] == str(barcode)].copy()
        if sub.empty:
            return []
        sub = sub.sort_values("price_cad", ascending=True)
        results = sub.to_dict(orient="records")
        return results

    def best_price(self, barcode: str) -> Optional[Dict[str, Any]]:
        results = self.find_prices(barcode)
        return results[0] if results else None
