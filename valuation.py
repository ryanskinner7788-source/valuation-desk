"""
valuation.py
------------
Pure valuation math: CAPM / WACC, a 2-stage FCFF discounted cash flow model,
and a Gordon Growth dividend discount model.

Every function here takes plain numbers (floats/ints/None) — never a yfinance
object, never a network call. That split matters for two reasons:
1. Data pulled from Yahoo Finance is frequently messy or missing fields, and
   this module should not care why a number is missing, only how to degrade
   gracefully when it is.
2. It makes the math independently testable (see test_valuation.py).

All rates are expressed as decimals (0.08 = 8%), not percentages.
"""

from dataclasses import dataclass, field
from typing import Optional, List


# ----------------------------------------------------------------------------
# Assumptions — the only "opinions" baked into the model. Change these if you
# have a different house view; everything downstream just consumes them.
# ----------------------------------------------------------------------------
EQUITY_RISK_PREMIUM = 0.05      # long-run US equity risk premium
DEFAULT_RISK_FREE_RATE = 0.0425 # used only if a live 10Y yield can't be fetched
TERMINAL_GROWTH_RATE = 0.03     # perpetuity growth, ~ long-run nominal GDP
DEFAULT_TAX_RATE = 0.25         # effective tax rate fallback
PROJECTION_YEARS = 10           # a longer explicit window suits stable, mature compounders
MAX_YEAR1_GROWTH = 0.30         # sanity ceiling on the first projected year's growth
MIN_YEAR1_GROWTH = -0.20        # sanity floor (lets a shrinking business still resolve)
MAX_DIVIDEND_GROWTH = 0.10      # sanity ceiling for DDM growth assumption


# ----------------------------------------------------------------------------
# WACC / CAPM
# ----------------------------------------------------------------------------

@dataclass
class WaccResult:
    wacc: float
    cost_of_equity: float
    cost_of_debt_after_tax: float
    weight_equity: float
    weight_debt: float
    risk_free_rate: float
    beta: float
    tax_rate: float


def calculate_cost_of_equity(risk_free_rate: float, beta: float,
                              erp: float = EQUITY_RISK_PREMIUM) -> float:
    """CAPM: Re = Rf + Beta * ERP"""
    return risk_free_rate + beta * erp


def calculate_wacc(
    market_cap: Optional[float],
    total_debt: Optional[float],
    interest_expense: Optional[float],
    pretax_income: Optional[float],
    tax_provision: Optional[float],
    beta: Optional[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> WaccResult:
    """
    Weighted-average cost of capital. Falls back to sane defaults for any
    input that's missing or out of a plausible range, rather than raising —
    a single missing balance-sheet field shouldn't take down the whole model.
    """
    beta = beta if (beta and beta > 0) else 1.0

    cost_of_equity = calculate_cost_of_equity(risk_free_rate, beta)

    tax_rate = DEFAULT_TAX_RATE
    if pretax_income and tax_provision is not None and pretax_income > 0:
        computed = tax_provision / pretax_income
        if 0 <= computed <= 0.45:
            tax_rate = computed

    cost_of_debt_pretax = 0.05
    if interest_expense and total_debt and total_debt > 0:
        computed_cod = abs(interest_expense) / total_debt
        if 0 < computed_cod <= 0.20:
            cost_of_debt_pretax = computed_cod

    cost_of_debt_after_tax = cost_of_debt_pretax * (1 - tax_rate)

    market_cap = market_cap or 0
    total_debt = total_debt or 0
    total_capital = market_cap + total_debt

    if total_capital <= 0:
        weight_equity, weight_debt = 1.0, 0.0
    else:
        weight_equity = market_cap / total_capital
        weight_debt = total_debt / total_capital

    wacc = weight_equity * cost_of_equity + weight_debt * cost_of_debt_after_tax
    wacc = max(wacc, 0.04)  # floor so a bad input can't produce a nonsensical near-zero discount rate

    return WaccResult(
        wacc=wacc,
        cost_of_equity=cost_of_equity,
        cost_of_debt_after_tax=cost_of_debt_after_tax,
        weight_equity=weight_equity,
        weight_debt=weight_debt,
        risk_free_rate=risk_free_rate,
        beta=beta,
        tax_rate=tax_rate,
    )


# ----------------------------------------------------------------------------
# Shared helper
# ----------------------------------------------------------------------------

def calculate_cagr(begin_value: Optional[float], end_value: Optional[float],
                    periods: float) -> Optional[float]:
    """Compound annual growth rate between two values. Returns None (rather
    than a misleading number) whenever either value is non-positive, since a
    CAGR through a loss-making or negative-FCF year isn't meaningful."""
    if not begin_value or begin_value <= 0 or not end_value or end_value <= 0 or periods <= 0:
        return None
    try:
        return (end_value / begin_value) ** (1 / periods) - 1
    except (ValueError, ZeroDivisionError):
        return None


# ----------------------------------------------------------------------------
# DCF (2-stage FCFF)
# ----------------------------------------------------------------------------

@dataclass
class DcfResult:
    available: bool
    fair_value_per_share: Optional[float] = None
    enterprise_value: Optional[float] = None
    equity_value: Optional[float] = None
    projected_fcf: List[float] = field(default_factory=list)
    discount_rate: float = 0.0
    growth_year1: float = 0.0
    terminal_growth: float = 0.0
    reason: Optional[str] = None


def project_fcf(base_fcf: float, growth_year1: float, terminal_growth: float,
                 years: int = PROJECTION_YEARS) -> List[float]:
    """
    2-stage FCF projection: the growth rate fades linearly from growth_year1
    in year 1 down to terminal_growth by the final projected year, rather
    than jumping straight to a terminal rate. This avoids the classic DCF
    artifact where a high near-term growth rate is (unrealistically) assumed
    to hold right up until the last projected year.
    """
    fcfs = []
    prev = base_fcf
    for yr in range(1, years + 1):
        g = growth_year1 + (terminal_growth - growth_year1) * (yr - 1) / max(years - 1, 1)
        prev = prev * (1 + g)
        fcfs.append(prev)
    return fcfs


def run_dcf(
    base_fcf: Optional[float],
    growth_year1: Optional[float],
    wacc: float,
    total_debt: Optional[float],
    total_cash: Optional[float],
    shares_outstanding: Optional[float],
    terminal_growth: float = TERMINAL_GROWTH_RATE,
) -> DcfResult:
    if not base_fcf or base_fcf <= 0:
        return DcfResult(available=False,
                          reason="No positive free cash flow history to build a projection from.")
    if not shares_outstanding or shares_outstanding <= 0:
        return DcfResult(available=False, reason="Shares outstanding unavailable.")

    growth_year1 = terminal_growth if growth_year1 is None else growth_year1
    growth_year1 = max(min(growth_year1, MAX_YEAR1_GROWTH), MIN_YEAR1_GROWTH)

    if terminal_growth >= wacc:
        terminal_growth = max(wacc - 0.01, 0.005)

    fcfs = project_fcf(base_fcf, growth_year1, terminal_growth)

    discounted_fcfs = [fcf / ((1 + wacc) ** yr) for yr, fcf in enumerate(fcfs, start=1)]
    terminal_value = fcfs[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    discounted_terminal_value = terminal_value / ((1 + wacc) ** len(fcfs))

    enterprise_value = sum(discounted_fcfs) + discounted_terminal_value
    equity_value = enterprise_value - (total_debt or 0) + (total_cash or 0)
    fair_value_per_share = equity_value / shares_outstanding

    return DcfResult(
        available=True,
        fair_value_per_share=fair_value_per_share,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        projected_fcf=fcfs,
        discount_rate=wacc,
        growth_year1=growth_year1,
        terminal_growth=terminal_growth,
    )


# ----------------------------------------------------------------------------
# DDM (Gordon Growth)
# ----------------------------------------------------------------------------

@dataclass
class DdmResult:
    available: bool
    fair_value_per_share: Optional[float] = None
    dividend_growth: float = 0.0
    required_return: float = 0.0
    reason: Optional[str] = None


def run_ddm(
    current_annual_dividend: Optional[float],
    dividend_growth: Optional[float],
    required_return: float,
) -> DdmResult:
    if not current_annual_dividend or current_annual_dividend <= 0:
        return DdmResult(available=False, required_return=required_return,
                          reason="This company does not currently pay a dividend.")

    g = 0.03 if dividend_growth is None else dividend_growth
    g = max(min(g, MAX_DIVIDEND_GROWTH), 0.0)

    if g >= required_return:
        g = max(required_return - 0.01, 0.0)

    d1 = current_annual_dividend * (1 + g)
    fair_value = d1 / (required_return - g)

    return DdmResult(available=True, fair_value_per_share=fair_value,
                      dividend_growth=g, required_return=required_return)
