# Valuation Desk

Type a ticker, get analyst targets, a DCF, a DDM, relative valuation, a price
chart, and recent news — built to run as an iPhone home-screen app.

## Files

- `main.py` — FastAPI app, one endpoint: `GET /api/analyze/{ticker}`
- `data_fetch.py` — all Yahoo Finance (yfinance) calls, defensively wrapped
- `valuation.py` — pure DCF / DDM / WACC math, no network, unit-tested
- `test_valuation.py` — sanity tests for the math (`python3 test_valuation.py`)
- `static/` — the mobile frontend (vanilla HTML/CSS/JS + Chart.js)
- `render.yaml` — optional deploy blueprint for Render

## Run locally

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open http://127.0.0.1:8000

## Notes

- Data comes from Yahoo Finance via the unofficial `yfinance` library —
  intended for personal use, and occasionally flaky by nature (Yahoo doesn't
  publish a supported API). The app is written to degrade gracefully rather
  than crash when a field is missing for a given ticker.
- DCF/DDM assumptions (risk-free rate fallback, equity risk premium, terminal
  growth) are constants at the top of `valuation.py` — tune them to your own
  view any time.
