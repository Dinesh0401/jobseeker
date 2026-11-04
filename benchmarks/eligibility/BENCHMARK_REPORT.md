# Job Hunter v2.3 — 100-Job Eligibility Benchmark Audit Report

## Executive Summary

- **Total Dataset Samples:** 100
- **Exact Actionability Matches:** 98/100 (98.0%)
- **Binary Actionability Accuracy:** 100.0%
- **Precision:** 100.0%
- **Recall:** 100.0%
- **F1 Score:** 100.0
- **CRITICAL False Positives (Unsafe Classifications):** **0**
- **False Negatives (Missed Opportunities):** **0**

## 1. Safety Gate Verdict

> [!IMPORTANT]
> **PASSED CRITICAL SAFETY GATE (0 False Positives)**: Zero ineligible or ambiguous postings were classified as actionable. No unauthorized application or CV generation can be triggered.

## 2. 4x4 Actionability Confusion Matrix

| Ground Truth \ Predicted | CONFIRMED_ELIGIBLE | RELOCATION_PATHWAY | PENDING_LOCATION_VERIFICATION (HOLD) | INELIGIBLE |
| :--- | :---: | :---: | :---: | :---: |
| **CONFIRMED_ELIGIBLE** | 26 | 0 | 0 | 0 |
| **RELOCATION_PATHWAY** | 0 | 12 | 0 | 0 |
| **PENDING_LOCATION_VERIFICATION** | 0 | 0 | 10 | 0 |
| **INELIGIBLE** | 0 | 0 | 2 | 50 |

## 3. Category-Level Performance Metrics

| Category Group | Total | Exact Correct | Precision | Recall | F1 | False Positives | False Negatives | Held for Verification |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Explicitly Eligible from India** | 12 | 12 (100.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 0 |
| **Worldwide Remote** | 14 | 14 (100.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 0 |
| **Worldwide Remote with India Exclusion** | 4 | 4 (100.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 0 |
| **Other** | 16 | 16 (100.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 0 |
| **Remote Restricted to Specific Countries** | 19 | 18 (94.74%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 2 |
| **EU-Only & Germany-Only Remote** | 11 | 11 (100.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 0 |
| **Time-Zone Restricted Roles** | 2 | 1 (50.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 1 |
| **Relocation-Supported Opportunities** | 11 | 11 (100.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 0 |
| **Relocation without Sponsorship / Work Auth Required** | 2 | 2 (100.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 0 |
| **Ambiguous Remote Eligibility** | 5 | 5 (100.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 5 |
| **Missing Location Information** | 4 | 4 (100.0%) | 100.0% | 100.0% | 100.0 | **0** | 0 | 4 |

## 4. Misclassified Cases & Error Analysis

| ID | Title | Group | Expected | Predicted | Responsible Rule / Gap | Recommended Correction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `BENCH-059` | Junior AI Support Engineer | Remote Restricted to Specific Countries | `INELIGIBLE` | `PENDING_LOCATION_VERIFICATION` | Fallback to ELIGIBILITY_UNKNOWN because no positive or negative regex triggered. | Add pattern to recognize this specific geographic indicator. |
| `BENCH-061` | Associate LLM Evaluator | Time-Zone Restricted Roles | `INELIGIBLE` | `PENDING_LOCATION_VERIFICATION` | Fallback to ELIGIBILITY_UNKNOWN because no positive or negative regex triggered. | Add pattern to recognize this specific geographic indicator. |
