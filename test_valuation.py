"""
Quick sanity tests for valuation.py using plain hand-picked numbers
(roughly the scale of a real mid/large-cap). Run with: python3 test_valuation.py
No network, no yfinance, no fastapi required — just checks the math holds together.
"""
from valuation import calculate_wacc, run_dcf, run_ddm, calculate_cagr, calculate_cost_of_equity


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


print("=== WACC ===")
wacc_result = calculate_wacc(
    market_cap=500_000_000_000,
    total_debt=100_000_000_000,
    interest_expense=3_000_000_000,
    pretax_income=40_000_000_000,
    tax_provision=8_000_000_000,
    beta=1.15,
)
print(wacc_result)
check("WACC is between 4% and 15%", 0.04 <= wacc_result.wacc <= 0.15)
check("weights sum to 1", abs(wacc_result.weight_equity + wacc_result.weight_debt - 1) < 1e-9)
check("tax rate used the computed 20%", abs(wacc_result.tax_rate - 0.20) < 1e-9)

print("\n=== WACC with missing debt data (should still resolve, not crash) ===")
wacc_no_debt_data = calculate_wacc(
    market_cap=50_000_000_000, total_debt=5_000_000_000,
    interest_expense=None, pretax_income=None, tax_provision=None, beta=None,
)
print(wacc_no_debt_data)
check("beta defaulted to 1.0", wacc_no_debt_data.beta == 1.0)
check("tax rate defaulted to 25%", abs(wacc_no_debt_data.tax_rate - 0.25) < 1e-9)

print("\n=== DCF: healthy growing company ===")
dcf = run_dcf(
    base_fcf=20_000_000_000,
    growth_year1=0.12,
    wacc=wacc_result.wacc,
    total_debt=100_000_000_000,
    total_cash=60_000_000_000,
    shares_outstanding=7_500_000_000,
)
print(dcf)
check("DCF available", dcf.available)
check("fair value per share is positive and plausible ($1-$1000)", dcf.fair_value_per_share is not None and 1 < dcf.fair_value_per_share < 1000)
check("10 years projected", len(dcf.projected_fcf) == 10)
check("FCF grows from year 1 to year 2 when growth > terminal", dcf.projected_fcf[1] > dcf.projected_fcf[0])

print("\n=== DCF: negative FCF (should degrade gracefully, not crash) ===")
dcf_bad = run_dcf(
    base_fcf=-500_000_000, growth_year1=0.05, wacc=0.09,
    total_debt=1_000_000_000, total_cash=200_000_000, shares_outstanding=100_000_000,
)
print(dcf_bad)
check("DCF correctly marked unavailable for negative FCF", not dcf_bad.available)
check("reason is populated", bool(dcf_bad.reason))

print("\n=== DCF: terminal growth >= WACC edge case gets capped, not a crash ===")
dcf_edge = run_dcf(
    base_fcf=1_000_000, growth_year1=0.03, wacc=0.03,
    total_debt=0, total_cash=0, shares_outstanding=1_000_000,
    terminal_growth=0.03,
)
print(dcf_edge)
check("still resolves to a positive value despite g==WACC input", dcf_edge.available and dcf_edge.fair_value_per_share > 0)

print("\n=== DDM: dividend payer ===")
ddm = run_ddm(current_annual_dividend=2.40, dividend_growth=0.06,
              required_return=calculate_cost_of_equity(0.0425, 1.05))
print(ddm)
check("DDM available", ddm.available)
check("fair value positive", ddm.fair_value_per_share > 0)

print("\n=== DDM: non-payer ===")
ddm_none = run_ddm(current_annual_dividend=0, dividend_growth=None, required_return=0.08)
print(ddm_none)
check("DDM correctly unavailable", not ddm_none.available)

print("\n=== DDM: growth >= required return gets capped, not a ZeroDivisionError ===")
ddm_edge = run_ddm(current_annual_dividend=1.0, dividend_growth=0.20, required_return=0.08)
print(ddm_edge)
check("DDM still resolves", ddm_edge.available and ddm_edge.fair_value_per_share > 0)
check("growth was capped below required return", ddm_edge.dividend_growth < 0.08)

print("\n=== CAGR helper ===")
check("normal CAGR", abs(calculate_cagr(100, 200, 5) - (2 ** (1/5) - 1)) < 1e-9)
check("negative begin value -> None", calculate_cagr(-100, 200, 5) is None)
check("zero periods -> None", calculate_cagr(100, 200, 0) is None)

print("\nAll checks passed.")
