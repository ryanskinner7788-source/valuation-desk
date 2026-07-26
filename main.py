"""
main.py
-------
FastAPI app for Valuation Desk. One real endpoint — GET /api/analyze/{ticker}
— that fetches everything from Yahoo Finance, runs the DCF/DDM/WACC math,
and returns a single JSON payload. Every section is wrapped independently so
a problem in, say, the dividend history never takes down the price chart or
the analyst targets.
"""
import math
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

import data_fetch
import valuation

app = FastAPI(title="Valuation Desk API")


def _sanitize_for_json(obj):
    """
    Recursively replace NaN/Infinity floats with None.
    Yahoo Finance data occasionally contains NaN, and Python's json module
    will happily write that as a literal `NaN` token — which is accepted by
    Python's own parser but is NOT valid JSON, so browsers reject it outright
    (surfacing as a generic "failed to fetch" with no useful detail). This
    runs once, right before the response goes out, so no individual field
    needs its own NaN-guard.
    """
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _valuation_gap_note(fair_value, current_price, model_name):
    """
    A DCF or DDM fair value that's very far from the current price usually
    means the assumptions (discount rate, growth durability) don't match
    what the market is pricing in — not that the model is broken or the
    stock is mispriced. This is most visible for two common cases: richly
    valued, high-quality compounders (where a textbook discount rate makes
    the DCF undershoot badly) and out-of-favor or declining businesses
    (where it can overshoot). Surfacing that plainly beats presenting a
    lone number with no context.
    """
    if not fair_value or not current_price:
        return None
    gap = (fair_value - current_price) / current_price
    if abs(gap) < 0.35:
        return None
    direction = "well below" if gap < 0 else "well above"
    return (f"This {model_name} value is {direction} the current price. A gap this large usually means "
            f"the assumptions above (discount rate, growth) don't match what the market is pricing in for "
            f"this stock, rather than the stock being mispriced — {model_name} tends to undershoot for "
            f"expensive, high-quality compounders and can overshoot for struggling ones. Worth treating as "
            f"a prompt to question the assumptions, not a verdict.")


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/analyze/{ticker}")
def analyze(ticker: str, peers: Optional[str] = Query(default=None,
            description="Optional comma-separated peer tickers, e.g. MSFT,GOOGL")):
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 12:
        raise HTTPException(status_code=400, detail="Enter a valid ticker symbol.")

    tkr = data_fetch.get_ticker(ticker)
    snapshot = data_fetch.fetch_snapshot(tkr)

    if snapshot.get("current_price") is None and not snapshot.get("name"):
        raise HTTPException(status_code=404,
                             detail=f"Couldn't find data for '{ticker}'. Check the symbol and try again.")

    # ---- Analyst targets -----------------------------------------------
    try:
        analyst_targets = data_fetch.fetch_analyst_targets(tkr)
    except Exception:
        analyst_targets = {"available": False}

    # ---- Risk-free rate + WACC -------------------------------------------
    risk_free_rate = data_fetch.fetch_risk_free_rate()
    try:
        dcf_inputs = data_fetch.fetch_dcf_inputs(tkr)
    except Exception:
        dcf_inputs = {"base_fcf": None, "growth_year1": None, "interest_expense": None,
                       "pretax_income": None, "tax_provision": None, "fcf_history": []}

    wacc_result = valuation.calculate_wacc(
        market_cap=snapshot.get("market_cap"),
        total_debt=snapshot.get("total_debt"),
        interest_expense=dcf_inputs.get("interest_expense"),
        pretax_income=dcf_inputs.get("pretax_income"),
        tax_provision=dcf_inputs.get("tax_provision"),
        beta=snapshot.get("beta"),
        risk_free_rate=risk_free_rate,
    )

    # ---- DCF ---------------------------------------------------------------
    try:
        dcf_result = valuation.run_dcf(
            base_fcf=dcf_inputs.get("base_fcf"),
            growth_year1=dcf_inputs.get("growth_year1"),
            wacc=wacc_result.wacc,
            total_debt=snapshot.get("total_debt"),
            total_cash=snapshot.get("total_cash"),
            shares_outstanding=snapshot.get("shares_outstanding"),
        )
    except Exception as e:
        dcf_result = valuation.DcfResult(available=False, reason=f"DCF could not be computed ({e}).")

    # ---- DDM -----------------------------------------------------------
    try:
        dividend_growth = data_fetch.fetch_dividend_growth(tkr)
        ddm_result = valuation.run_ddm(
            current_annual_dividend=snapshot.get("dividend_rate"),
            dividend_growth=dividend_growth,
            required_return=wacc_result.cost_of_equity,
        )
    except Exception as e:
        ddm_result = valuation.DdmResult(available=False, reason=f"DDM could not be computed ({e}).")

    # ---- Relative valuation (own multiples + optional peers) -------------
    relative_valuation = {
        "multiples": {
            "trailing_pe": snapshot.get("trailing_pe"),
            "forward_pe": snapshot.get("forward_pe"),
            "price_to_sales": snapshot.get("price_to_sales"),
            "price_to_book": snapshot.get("price_to_book"),
            "ev_to_ebitda": snapshot.get("ev_to_ebitda"),
            "peg_ratio": snapshot.get("peg_ratio"),
        },
        "fifty_two_week_low": snapshot.get("fifty_two_week_low"),
        "fifty_two_week_high": snapshot.get("fifty_two_week_high"),
        "current_price": snapshot.get("current_price"),
        "peers": [],
    }
    if peers:
        peer_symbols = [p.strip().upper() for p in peers.split(",") if p.strip()][:6]
        for sym in peer_symbols:
            if sym == ticker:
                continue
            try:
                peer_data = data_fetch.fetch_peer_snapshot(sym)
                if peer_data:
                    relative_valuation["peers"].append(peer_data)
            except Exception:
                continue

    # ---- Price chart -----------------------------------------------------
    try:
        price_chart = data_fetch.fetch_price_history(tkr)
    except Exception:
        price_chart = []

    # ---- News --------------------------------------------------------------
    try:
        news = data_fetch.fetch_news(tkr)
    except Exception:
        news = []

    # ---- Valuation summary (for the comparison bar chart) -----------------
    valuation_summary = {
        "current_price": snapshot.get("current_price"),
        "dcf_fair_value": dcf_result.fair_value_per_share if dcf_result.available else None,
        "ddm_fair_value": ddm_result.fair_value_per_share if ddm_result.available else None,
        "analyst_mean_target": analyst_targets.get("mean"),
        "analyst_low_target": analyst_targets.get("low"),
        "analyst_high_target": analyst_targets.get("high"),
    }

    dcf_dict = asdict(dcf_result)
    if dcf_result.available:
        dcf_dict["gap_note"] = _valuation_gap_note(
            dcf_result.fair_value_per_share, snapshot.get("current_price"), "DCF")

    ddm_dict = asdict(ddm_result)
    if ddm_result.available:
        ddm_dict["gap_note"] = _valuation_gap_note(
            ddm_result.fair_value_per_share, snapshot.get("current_price"), "DDM")

    result = {
        "symbol": ticker,
        "snapshot": snapshot,
        "analyst_targets": analyst_targets,
        "wacc": asdict(wacc_result),
        "dcf": dcf_dict,
        "ddm": ddm_dict,
        "relative_valuation": relative_valuation,
        "price_chart": price_chart,
        "valuation_summary": valuation_summary,
        "news": news,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return _sanitize_for_json(result)


# Serve the frontend. Must be mounted after the /api routes above so it
# doesn't shadow them.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
