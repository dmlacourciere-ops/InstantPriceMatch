# providers/off_loader.py
import os
import pandas as pd
from typing import List, Dict
from rapidfuzz import process, fuzz

# Use the mirrored CSV the scraper wrote
LATEST_CSV = r"F:\Docs\off_data\latest\off_canada_products.csv"

def _load_latest_csv(path: str = LATEST_CSV) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Latest CSV not found at {path}.\n"
            "Let the scraper finish OR temporarily point LATEST_CSV to a runs/<timestamp>/off_canada_products.csv"
        )
    usecols = ["barcode", "product_name", "brand", "quantity", "categories", "image_url"]
    df = pd.read_csv(path, usecols=usecols, dtype=str).fillna("")
    # helper column for fuzzy search
    df["search_text"] = (df["brand"] + " " + df["product_name"] + " " + df["quantity"]).str.strip()
    # normalize UPC-only column
    df["barcode_digits"] = df["barcode"].str.replace(r"\D", "", regex=True)
    return df

def find_by_upc(upc: str, limit: int = 10) -> List[Dict]:
    df = _load_latest_csv()
    digits = "".join(c for c in upc if c.isdigit())
    rows = df[df["barcode_digits"] == digits].head(limit)
    return rows.to_dict(orient="records")

def search_by_name(query: str, limit: int = 10, score_cutoff: int = 65) -> List[Dict]:
    df = _load_latest_csv()
    choices = df["search_text"].tolist()
    matches = process.extract(query, choices, scorer=fuzz.WRatio, score_cutoff=score_cutoff, limit=limit)
    out = []
    for _, score, idx in matches:
        row = df.iloc[int(idx)].to_dict()
        row["match_score"] = int(score)
        out.append(row)
    return out
