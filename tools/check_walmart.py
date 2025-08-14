import importlib
import inspect
import os
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TOOLS_DIR)
PROVIDERS_DIR = os.path.join(ROOT_DIR, "providers")
for p in (ROOT_DIR, PROVIDERS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

def try_import():
    for name in ("walmart_playwright", "providers.walmart_playwright"):
        try:
            mod = importlib.import_module(name)
            return mod, name
        except Exception:
            continue
    return None, "not found"

def main():
    print("CWD:", os.getcwd())
    print("Root shim exists:", os.path.exists(os.path.join(ROOT_DIR, "walmart_playwright.py")))
    print("Providers file exists:", os.path.exists(os.path.join(PROVIDERS_DIR, "walmart_playwright.py")))
    mod, name = try_import()
    if mod is None:
        print("\nERROR: Could not import walmart_playwright (tried root shim and providers path).")
        return
    print("\nLoaded:", name, "from:", getattr(mod, "__file__", "(unknown)"))
    funcs = [n for n, o in inspect.getmembers(mod, inspect.isfunction)]
    print("\nFunctions found:")
    for n in funcs:
        print(" -", n)
    print("\nCallable candidates:")
    for candidate in ["lookup_by_upc_or_name","lookup_by_upc","by_upc","lookup_upc",
                      "lookup_by_name","search","by_name","lookup_name","query","lookup","find",
                      "walmart_lookup_playwright"]:
        f = getattr(mod, candidate, None)
        print(("  ✓" if callable(f) else "  ✗"), candidate)

if __name__ == "__main__":
    main()
