import pandas as pd, requests, sys
from pathlib import Path
CSV = r"F:\Docs\off_data\latest\off_canada_products.csv"
UA  = {"User-Agent":"InstantPriceMatch/0.1"}

def seg(c): return f"{c[0:3]}/{c[3:6]}/{c[6:9]}/{c[9:]}" if len(c)>9 else c

def url_variants(code):
    return [
        f"https://images.openfoodfacts.org/v2/product/{code}/front/400.jpg",
        f"https://images.openfoodfacts.org/v2/product/{code}/front/200.jpg",
        f"https://images.openfoodfacts.org/v2/product/{code}/front/100.jpg",
        f"https://images.openfoodfacts.org/v2/product/{code}/front/full.jpg",
        f"https://images.openfoodfacts.org/images/products/{seg(code)}/front_en.400.jpg",
        f"https://images.openfoodfacts.org/images/products/{seg(code)}/front_en.200.jpg",
        f"https://images.openfoodfacts.org/images/products/{seg(code)}/front_en.100.jpg",
        f"https://images.openfoodfacts.org/images/products/{seg(code)}/front.400.jpg",
        f"https://images.openfoodfacts.org/images/products/{seg(code)}/front.200.jpg",
        f"https://images.openfoodfacts.org/images/products/{seg(code)}/front.100.jpg",
    ]

ok = []
for chunk in pd.read_csv(CSV, chunksize=1000):
    for _,row in chunk.iterrows():
        code = str(row.get("barcode") or row.get("code") or "").strip()
        if not code: continue
        for u in url_variants(code):
            try:
                r = requests.get(u, timeout=15, headers=UA)
                if r.status_code==200 and len(r.content)>1024:
                    ok.append((code, u))
                    print(f"[OK] {code} -> {u}")
                    break
            except: pass
        if len(ok)>=20:
            break
    if len(ok)>=20:
        break

print(f"\nFound {len(ok)} working images.")
