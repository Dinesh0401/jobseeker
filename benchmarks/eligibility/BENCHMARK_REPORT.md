# Job Hunter v2.2 — 100-Job Eligibility Benchmark Audit Report

- **Total Evaluated Cases:** 100
- **Overall Actionability Accuracy:** 100.0% (100/100)
- **CRITICAL False Eligible Count (Safety Defects):** 0
- **False Ineligible Count (Missed Opportunities):** 0
- **Cases Placed on Hold for Verification:** 8

## 1. Safety Audit Verdict

> [!IMPORTANT]
> **PASSED SAFETY GATE**: Zero false-eligible classifications detected across all 100 benchmark postings. No ineligible or ambiguous posting bypassed location gates.

## 2. Category Performance Breakdown

| Category Group | Total Cases | Correct | False Eligible (Unsafe) | False Ineligible (Missed) | Held for Verification |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Worldwide Remote** | 18 | 18 | **0** | 0 | 0 |
| **India Eligible Remote** | 14 | 14 | **0** | 0 | 0 |
| **Relocation + Sponsorship** | 14 | 14 | **0** | 0 | 0 |
| **Relocation without Sponsorship** | 10 | 10 | **0** | 0 | 0 |
| **Explicit India Exclusion** | 12 | 12 | **0** | 0 | 0 |
| **Country Restricted** | 14 | 14 | **0** | 0 | 0 |
| **Germany Remote** | 6 | 6 | **0** | 0 | 0 |
| **Europe Remote** | 4 | 4 | **0** | 0 | 0 |
| **Ambiguous / Needs Verification** | 8 | 8 | **0** | 0 | 8 |

## 3. Actionability Confusion Matrix

| Expected \ Predicted | CONFIRMED_ELIGIBLE | RELOCATION_PATHWAY | PENDING_LOCATION_VERIFICATION | INELIGIBLE |
| :--- | :---: | :---: | :---: | :---: |
| **CONFIRMED_ELIGIBLE** | 32 | 0 | 0 | 0 |
| **RELOCATION_PATHWAY** | 0 | 14 | 0 | 0 |
| **PENDING_LOCATION_VERIFICATION** | 0 | 0 | 8 | 0 |
| **INELIGIBLE** | 0 | 0 | 0 | 46 |
