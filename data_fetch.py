"""
data_fetch.py
-------------
Every external call to Yahoo Finance (via yfinance) lives here, isolated from
valuation.py's pure math. Yahoo's underlying data (accessed through yfinance's
unofficial endpoints) is genuinely inconsistent — field names and statement
row labels shift across tickers, exchanges, and library versions — so almost
everything in this file is written to degrade to `None` / an empty structure
rather than raise, and callers are expected to check for that.

Data via Yahoo Finance, for personal research use.
"""
import math
from datetime import datetime
from typing import Optional, Any

import pandas as pd
import yfinance as yf

from valuation import calculate_cagr

DEFAULT_RISK_FREE_RATE = 0.0425


# ----------------------------------------------------------------------------
# Small generic helpers
# ----------------------------------------------------------------------------

def _safe(d: Optional[dict], key: str, default=None):
    if not d:
        return default
    val = d.get(key, default)
    return val if val is not None else default


def _find_row(df: Optional[pd.DataFrame], *keywords: str):
    """
    Find a row in a yfinance financial-statement DataFrame whose label
    contains ANY of the given keywords (case-insensitive substring match).
    Returns the row as a pandas Series (columns = report dates) or None.
    Using substring matching instead of exact labels is deliberate: Yahoo's
    statement line-item names have changed wording across yfinance versions,
    and this keeps the app working across that drift.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for label in df.index:
        label_lower = str(label).lower()
        if any(kw.lower() in label_lower for kw in keywords):
            return df.loc[label]
    return None


def _series_to_sorted_pairs(series: Optional[pd.Series]):
    """Return [(date, value), ...] sorted oldest -> newest, dropping NaNs."""
    if series is None:
        return []
    pairs = [(col, val) for col, val in series.items() if val is not None and not (isinstance(val, float) and math.isnan(val))]
    pairs.sort(key=lambda p: p[0])
    return pairs


def _parse_news_timestamp(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


# ----------------------------------------------------------------------------
# Ticker object + snapshot
# ----------------------------------------------------------------------------

def get_ticker(symbol: str) -> yf.Ticker:
    return yf.Ticker(symbol.strip().upper())


def fetch_snapshot(tkr: yf.Ticker) -> dict:
    """Identity + current price + key ratios. Never raises."""
    try:
        info = tkr.info or {}
    except Exception:
        info = {}

    current_price = _safe(info, "currentPrice", _safe(info, "regularMarketPrice"))
    previous_close = _safe(info, "previousClose", _safe(info, "regularMarketPreviousClose"))

    if current_price is None:
        try:
            fast = tkr.fast_info
            current_price = getattr(fast, "last_price", None)
            if previous_close is None:
                previous_close = getattr(fast, "previous_close", None)
        except Exception:
            pass

    change = None
    change_pct = None
    if current_price is not None and previous_close:
        change = current_price - previous_close
        change_pct = (change / previous_close) * 100 if previous_close else None

    sector = _safe(info, "sector")
    industry = _safe(info, "industry")
    dcf_caveat = None
    combined = f"{sector or ''} {industry or ''}".lower()
    if any(kw in combined for kw in ["bank", "insurance", "reit", "real estate", "capital markets"]):
        dcf_caveat = ("This sector's cash-flow profile doesn't map cleanly onto a standard FCFF "
                      "DCF — treat the DCF figure below as a rough anchor rather than a precise one.")

    # Compute yield ourselves from dividend-rate / price (both plain dollar
    # figures) instead of trusting yfinance's dividendYield field directly —
    # that field's unit convention (a fraction like 0.008, vs. a whole
    # percent like 0.8) has changed across yfinance versions, so relying on
    # it directly risks silently showing a number 100x off.
    dividend_rate = _safe(info, "dividendRate")
    computed_dividend_yield = None
    if dividend_rate and current_price:
        computed_dividend_yield = dividend_rate / current_price

    ddm_caveat = None
    if dividend_rate and computed_dividend_yield is not None and computed_dividend_yield < 0.015:
        ddm_caveat = ("This dividend yield is low, so DDM only captures a small slice of what this "
                       "company actually returns to shareholders — many low-yield companies return "
                       "far more through buybacks, which DDM can't see at all. Treat this figure with "
                       "that in mind rather than as a full valuation.")

    return {
        "symbol": tkr.ticker,
        "name": _safe(info, "longName", _safe(info, "shortName", tkr.ticker)),
        "exchange": _safe(info, "exchange"),
        "currency": _safe(info, "currency", "USD"),
        "sector": sector,
        "industry": industry,
        "dcf_caveat": dcf_caveat,
        "ddm_caveat": ddm_caveat,
        "current_price": current_price,
        "previous_close": previous_close,
        "change": change,
        "change_pct": change_pct,
        "market_cap": _safe(info, "marketCap"),
        "shares_outstanding": _safe(info, "sharesOutstanding"),
        "beta": _safe(info, "beta"),
        "fifty_two_week_low": _safe(info, "fiftyTwoWeekLow"),
        "fifty_two_week_high": _safe(info, "fiftyTwoWeekHigh"),
        "trailing_pe": _safe(info, "trailingPE"),
        "forward_pe": _safe(info, "forwardPE"),
        "price_to_sales": _safe(info, "priceToSalesTrailing12Months"),
        "price_to_book": _safe(info, "priceToBook"),
        "peg_ratio": _safe(info, "trailingPegRatio", _safe(info, "pegRatio")),
        "enterprise_value": _safe(info, "enterpriseValue"),
        "ev_to_ebitda": _safe(info, "enterpriseToEbitda"),
        "total_debt": _safe(info, "totalDebt"),
        "total_cash": _safe(info, "totalCash"),
        "dividend_rate": dividend_rate,
        "dividend_yield": computed_dividend_yield if computed_dividend_yield is not None else _safe(info, "dividendYield"),
        "payout_ratio": _safe(info, "payoutRatio"),
    }


# ----------------------------------------------------------------------------
# Analyst targets
# ----------------------------------------------------------------------------

def fetch_analyst_targets(tkr: yf.Ticker) -> dict:
    result = {"available": False, "mean": None, "high": None, "low": None,
              "median": None, "num_analysts": None, "recommendation": None}
    try:
        targets = tkr.analyst_price_targets
        if targets:
            result.update({
                "mean": _safe(targets, "mean", _safe(targets, "current")),
                "high": _safe(targets, "high"),
                "low": _safe(targets, "low"),
                "median": _safe(targets, "median"),
            })
    except Exception:
        pass

    try:
        info = tkr.info or {}
        if result["mean"] is None:
            result["mean"] = _safe(info, "targetMeanPrice")
        if result["high"] is None:
            result["high"] = _safe(info, "targetHighPrice")
        if result["low"] is None:
            result["low"] = _safe(info, "targetLowPrice")
        if result["median"] is None:
            result["median"] = _safe(info, "targetMedianPrice")
        result["num_analysts"] = _safe(info, "numberOfAnalystOpinions")
        result["recommendation"] = _safe(info, "recommendationKey")
    except Exception:
        pass

    result["available"] = result["mean"] is not None
    return result


# ----------------------------------------------------------------------------
# Financial statement data for the DCF
# ----------------------------------------------------------------------------

def fetch_dcf_inputs(tkr: yf.Ticker) -> dict:
    """
    Pulls what valuation.run_dcf() needs: a base free-cash-flow figure, a
    year-1 growth estimate derived from FCF history, and balance-sheet items.
    Falls back gracefully at every step — a ticker with only 2 years of
    cash-flow history (recent IPO, thin coverage) still gets a best-effort
    base_fcf and simply skips the growth-trend calculation.
    """
    base_fcf = None
    growth_year1 = None

    try:
        cashflow = tkr.cashflow
    except Exception:
        cashflow = None

    fcf_row = _find_row(cashflow, "free cash flow")
    if fcf_row is None:
        ocf_row = _find_row(cashflow, "operating cash flow", "cash flow from operations",
                              "cash flow from operating activities", "total cash from operating")
        capex_row = _find_row(cashflow, "capital expenditure")
        if ocf_row is not None and capex_row is not None:
            fcf_row = ocf_row.add(capex_row, fill_value=0)  # capex is stored negative

    fcf_history = _series_to_sorted_pairs(fcf_row)
    if fcf_history:
        # Average the most recent up-to-3 years as the projection's starting
        # point, instead of using only the single latest year. One unusual
        # year (a capex spike, a working-capital swing) would otherwise set
        # the base for the entire 5-year projection on its own.
        recent_values = [v for _, v in fcf_history[-3:]]
        base_fcf = sum(recent_values) / len(recent_values)
        if len(fcf_history) >= 2:
            years = len(fcf_history) - 1
            # calculate_cagr() requires BOTH endpoints to be positive, which
            # correctly returns None (rather than a complex number) for a
            # company that had a down year in cash flow somewhere in its history.
            growth_year1 = calculate_cagr(fcf_history[0][1], fcf_history[-1][1], years)

    if growth_year1 is None:
        try:
            info = tkr.info or {}
            growth_year1 = _safe(info, "revenueGrowth")
        except Exception:
            pass

    try:
        income_stmt = tkr.income_stmt
    except Exception:
        income_stmt = None

    interest_expense = None
    pretax_income = None
    tax_provision = None
    ie_row = _find_row(income_stmt, "interest expense")
    pi_row = _find_row(income_stmt, "pretax income", "income before tax")
    tp_row = _find_row(income_stmt, "tax provision", "income tax expense")
    for row, target in ((ie_row, "ie"), (pi_row, "pi"), (tp_row, "tp")):
        pairs = _series_to_sorted_pairs(row)
        if pairs:
            if target == "ie":
                interest_expense = pairs[-1][1]
            elif target == "pi":
                pretax_income = pairs[-1][1]
            elif target == "tp":
                tax_provision = pairs[-1][1]

    return {
        "base_fcf": base_fcf,
        "growth_year1": growth_year1,
        "fcf_history": fcf_history,
        "interest_expense": interest_expense,
        "pretax_income": pretax_income,
        "tax_provision": tax_provision,
    }


# ----------------------------------------------------------------------------
# Dividend history for the DDM
# ----------------------------------------------------------------------------

def fetch_dividend_growth(tkr: yf.Ticker) -> Optional[float]:
    try:
        divs = tkr.dividends
        if divs is None or divs.empty:
            return None
        annual = divs.resample("YE").sum()
        annual = annual[annual > 0]
        if len(annual) < 2:
            return None
        years = len(annual) - 1
        begin, end = float(annual.iloc[0]), float(annual.iloc[-1])
        if begin <= 0:
            return None
        return (end / begin) ** (1 / years) - 1
    except Exception:
        return None


# ----------------------------------------------------------------------------
# Price history + moving averages (for the chart)
# ----------------------------------------------------------------------------

def fetch_price_history(tkr: yf.Ticker, period: str = "1y") -> list:
    try:
        hist = tkr.history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return []
        hist = hist.copy()
        hist["sma50"] = hist["Close"].rolling(window=50, min_periods=10).mean()
        hist["sma200"] = hist["Close"].rolling(window=200, min_periods=20).mean()
        points = []
        for idx, row in hist.iterrows():
            points.append({
                "date": idx.strftime("%Y-%m-%d"),
                "close": round(float(row["Close"]), 4),
                "sma50": None if pd.isna(row["sma50"]) else round(float(row["sma50"]), 4),
                "sma200": None if pd.isna(row["sma200"]) else round(float(row["sma200"]), 4),
            })
        return points
    except Exception:
        return []


# ----------------------------------------------------------------------------
# News
# ----------------------------------------------------------------------------

def fetch_news(tkr: yf.Ticker, limit: int = 8) -> list:
    items = []
    try:
        raw = tkr.news or []
    except Exception:
        raw = []

    for entry in raw:
        if len(items) >= limit:
            break
        try:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content")
            if content:  # newer nested shape
                title = content.get("title")
                provider = content.get("provider") or {}
                publisher = provider.get("displayName")
                url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
                link = url_obj.get("url")
                timestamp = _parse_news_timestamp(content.get("pubDate"))
            else:  # older flat shape
                title = entry.get("title")
                publisher = entry.get("publisher")
                link = entry.get("link")
                timestamp = _parse_news_timestamp(entry.get("providerPublishTime"))

            if title and link:
                items.append({
                    "title": title,
                    "publisher": publisher or "Unknown source",
                    "link": link,
                    "published_at": timestamp,
                })
        except Exception:
            continue
    return items


# ----------------------------------------------------------------------------
# Risk-free rate (10Y Treasury via ^TNX), with a bounds-checked fallback
# ----------------------------------------------------------------------------

def fetch_risk_free_rate() -> float:
    try:
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period="5d")
        if hist is not None and not hist.empty:
            last_close = float(hist["Close"].iloc[-1])
            if 0.5 <= last_close <= 20:
                return last_close / 100.0
            if 20 < last_close <= 200:
                return last_close / 1000.0
    except Exception:
        pass
    return DEFAULT_RISK_FREE_RATE


# ----------------------------------------------------------------------------
# Optional peer comparison
# ----------------------------------------------------------------------------

def fetch_peer_snapshot(symbol: str) -> Optional[dict]:
    try:
        tkr = get_ticker(symbol)
        info = tkr.info or {}
        price = _safe(info, "currentPrice", _safe(info, "regularMarketPrice"))
        if price is None:
            return None
        return {
            "symbol": tkr.ticker,
            "name": _safe(info, "shortName", tkr.ticker),
            "trailing_pe": _safe(info, "trailingPE"),
            "forward_pe": _safe(info, "forwardPE"),
            "ev_to_ebitda": _safe(info, "enterpriseToEbitda"),
            "price_to_sales": _safe(info, "priceToSalesTrailing12Months"),
            "price_to_book": _safe(info, "priceToBook"),
        }
    except Exception:
        return None
