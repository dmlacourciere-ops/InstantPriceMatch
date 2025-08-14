# Instant Price Match — Project Index

## Purpose
One-scan price match helper. Scan barcode → find cheapest local or online price → show cashier-friendly proof. [Add 1–2 sentences about current status]

## Tech Stack
Python 3.x, Playwright, [OCR/vision lib if planned], OS: Windows 10/11, IDE: VS Code

## Layout
- app.py — entry point
- /scrapers — walmart_playwright.py, bestbuy_playwright.py
- /ui — [CLI or simple GUI]
- /data — sample UPCs and outputs

## Env Keys (names only, no secrets)
OPENAI_API_KEY, [others]

## Key Modules
- walmart_playwright.py — lookup_by_upc_or_name [note responsibilities]
- bestbuy_playwright.py — [note responsibilities]
- vision pipeline — planned: image → product → fallback to scrapers

## Current Issues / TODO
- Fix AttributeError: walmart_playwright.lookup_by_upc_or_name not found
- Vision-first detection + fallback
- Tests and sample UPCs

## Minimal Repro
1) python -m venv .venv && .\.venv\Scripts\activate
2) pip install -r requirements.txt
3) playwright install
4) python app.py

## External Links
Repo: [fill in after publishing]
Assets root: [OneDrive link you’ll create later]
Screenshots: [optional OneDrive folder link]
