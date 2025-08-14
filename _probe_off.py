import pandas as pd, requests, os, sys, time
from pathlib import Path

CSV = r"F:\Docs\off_data\latest\off_canada_products.csv"
UA  = {"User-Agent":"InstantPriceMatch/0.1"}

def seg(code:str):
    code = code.strip()
    return f"{code[0:3]}/{code[3:6]}/{code[6:9]}/{code[9:]}" if len(code) > 9 else code

def try_one(url:str):
    try:
        r = requests.get(url, timeout=20, headers=UA)
        return r.status_code, len(r.content)
    except Exception as e:
        return f"ERR:{type(e).__name__}", 0

def first_working(code:str):
    patterns = [
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
    for u in patterns:
        status, n = try_one(u)
        print(f"  test {u} -> {status} ({n} bytes)")
        if status == 200 and n > 1024:
            return u
    return None

df = pd.read_csv(CSV, nrows=20)
for i, row in df.iterrows():
    code = str(row.get("barcode") or row.get("code") or "").strip()
    if not code: continue
    print(f"\nbarcode: {code} | name: {str(row.get('product_name',''))[:60]}")
    u = first_working(code)
    if u:
        print("[OK] first working image:", u)
        sys.exit(0)

print("\n[FAIL] No working image found in first 20 rows. Try increasing nrows.")
