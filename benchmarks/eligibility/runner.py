"""
Independent Evaluation Framework for Job Hunter v2.3 Eligibility Classification.
Calculates Confusion Matrix, Precision, Recall, F1 Score, False Positives, False Negatives,
and performs error analysis on misclassified cases without altering classifier logic.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, List

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.evaluators.eligibility import classify_eligibility, ActionabilityState, EligibilityCategory


def evaluate_dataset(cases_path: str = "benchmarks/eligibility/benchmark_cases.json") -> Dict[str, Any]:
    with open(cases_path, "r", encoding="utf-8") as f:
        cases: List[Dict[str, Any]] = json.load(f)

    # 4x4 Actionability Confusion Matrix
    act_labels = [
        "CONFIRMED_ELIGIBLE",
        "RELOCATION_PATHWAY",
        "PENDING_LOCATION_VERIFICATION",
        "INELIGIBLE"
    ]
    confusion_matrix = {exp: {pred: 0 for pred in act_labels} for exp in act_labels}

    # Binary Safety Classification: Actionable (Positive) vs Non-Actionable (Negative)
    # Positive = CONFIRMED_ELIGIBLE or RELOCATION_PATHWAY
    # Negative = PENDING_LOCATION_VERIFICATION or INELIGIBLE
    tp = 0
    fp = 0
    fn = 0
    tn = 0

    category_stats = defaultdict(lambda: {
        "total": 0,
        "correct": 0,
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "tn": 0,
        "held": 0,
    })

    misclassified_cases = []
    false_positives = []
    false_negatives = []

    for case in cases:
        c_id = case["id"]
        title = case["title"]
        location = case.get("location") or ""
        desc = case["description"]
        is_remote = case.get("is_remote", False)
        provenance = case.get("source_or_provenance", "Synthetic")
        reason = case.get("reason_for_expected", "")

        exp_cat = case["expected_category"]
        exp_act = case["expected_actionability"]
        exp_india = case["expected_can_apply_from_india"]

        # Infer category group
        group = _infer_group(c_id, exp_cat, exp_act, reason)
        category_stats[group]["total"] += 1

        # Run Deterministic Classifier
        assessment = classify_eligibility(
            title=title,
            location_str=location,
            description=desc,
            is_remote=is_remote,
        )

        pred_cat = assessment.category.value
        pred_act = assessment.actionability.value
        pred_india = assessment.can_apply_from_india

        # Update confusion matrix
        if exp_act in confusion_matrix and pred_act in confusion_matrix[exp_act]:
            confusion_matrix[exp_act][pred_act] += 1

        is_exp_positive = (exp_act in ["CONFIRMED_ELIGIBLE", "RELOCATION_PATHWAY"])
        is_pred_positive = (pred_act in ["CONFIRMED_ELIGIBLE", "RELOCATION_PATHWAY"])

        # Binary Metrics Update
        if is_exp_positive and is_pred_positive:
            tp += 1
            category_stats[group]["tp"] += 1
        elif not is_exp_positive and is_pred_positive:
            fp += 1
            category_stats[group]["fp"] += 1
        elif is_exp_positive and not is_pred_positive:
            fn += 1
            category_stats[group]["fn"] += 1
        else:
            tn += 1
            category_stats[group]["tn"] += 1

        if pred_act == "PENDING_LOCATION_VERIFICATION":
            category_stats[group]["held"] += 1

        # Multi-class correctness
        exact_match = (pred_act == exp_act) and (pred_india == exp_india)
        if exact_match:
            category_stats[group]["correct"] += 1
        else:
            # Diagnose responsible rule / root cause
            diag = _diagnose_discrepancy(
                desc=desc,
                location=location,
                evidence=assessment.evidence,
                exp_act=exp_act,
                pred_act=pred_act,
                exp_cat=exp_cat,
                pred_cat=pred_cat,
            )
            err_record = {
                "id": c_id,
                "title": title,
                "group": group,
                "location": location,
                "description": desc,
                "expected_category": exp_cat,
                "predicted_category": pred_cat,
                "expected_actionability": exp_act,
                "predicted_actionability": pred_act,
                "expected_can_apply_from_india": exp_india,
                "predicted_can_apply_from_india": pred_india,
                "evidence": assessment.evidence,
                "responsible_rule_or_gap": diag["responsible_rule"],
                "recommended_correction": diag["recommended_correction"],
            }
            misclassified_cases.append(err_record)

            if not is_exp_positive and is_pred_positive:
                false_positives.append(err_record)
            elif is_exp_positive and not is_pred_positive:
                false_negatives.append(err_record)

    total_cases = len(cases)
    precision = (tp / (tp + fp)) * 100 if (tp + fp) > 0 else 0.0
    recall = (tp / (tp + fn)) * 100 if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    overall_accuracy = ((tp + tn) / total_cases) * 100 if total_cases > 0 else 0.0
    exact_actionability_accuracy = ((total_cases - len(misclassified_cases)) / total_cases) * 100

    report = {
        "total_cases": total_cases,
        "exact_match_count": total_cases - len(misclassified_cases),
        "exact_match_accuracy_pct": round(exact_actionability_accuracy, 2),
        "binary_actionable_accuracy_pct": round(overall_accuracy, 2),
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "precision_pct": round(precision, 2),
        "recall_pct": round(recall, 2),
        "f1_score": round(f1, 2),
        "confusion_matrix": confusion_matrix,
        "category_metrics": {},
        "misclassified_cases": misclassified_cases,
        "false_positives_details": false_positives,
        "false_negatives_details": false_negatives,
    }

    # Category level metrics
    for grp, st in category_stats.items():
        g_tp = st["tp"]
        g_fp = st["fp"]
        g_fn = st["fn"]
        g_prec = (g_tp / (g_tp + g_fp) * 100) if (g_tp + g_fp) > 0 else (100.0 if g_fp == 0 else 0.0)
        g_rec = (g_tp / (g_tp + g_fn) * 100) if (g_tp + g_fn) > 0 else (100.0 if g_fn == 0 else 0.0)
        g_f1 = (2 * g_prec * g_rec / (g_prec + g_rec)) if (g_prec + g_rec) > 0 else 0.0
        report["category_metrics"][grp] = {
            "total": st["total"],
            "correct": st["correct"],
            "accuracy_pct": round((st["correct"] / st["total"]) * 100, 2) if st["total"] > 0 else 0.0,
            "false_positives": g_fp,
            "false_negatives": g_fn,
            "held_for_verification": st["held"],
            "precision_pct": round(g_prec, 2),
            "recall_pct": round(g_rec, 2),
            "f1_score": round(g_f1, 2),
        }

    # Save JSON report
    out_json = Path("benchmarks/eligibility/benchmark_report.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Generate Markdown Report
    _generate_markdown_report(report)

    return report


def _infer_group(c_id: str, exp_cat: str, exp_act: str, reason: str) -> str:
    r_lower = reason.lower()
    if "india" in r_lower and exp_act == "CONFIRMED_ELIGIBLE":
        return "Explicitly Eligible from India"
    if exp_cat == "WORLDWIDE_REMOTE":
        return "Worldwide Remote"
    if "override" in r_lower or "exclusion" in r_lower or "ineligible list" in r_lower or "except india" in r_lower:
        return "Worldwide Remote with India Exclusion"
    if "blue card" in r_lower or ("relocation" in r_lower and exp_act == "RELOCATION_PATHWAY"):
        return "Relocation-Supported Opportunities"
    if "cannot sponsor" in r_lower or "work authorization" in r_lower and "relocation" in r_lower:
        return "Relocation without Sponsorship / Work Auth Required"
    if "us " in r_lower or "canada" in r_lower or "uk " in r_lower or "australia" in r_lower:
        return "Remote Restricted to Specific Countries"
    if "deutschlandweit" in r_lower or "germany" in r_lower or "europe" in r_lower:
        return "EU-Only & Germany-Only Remote"
    if "timezone" in r_lower:
        return "Time-Zone Restricted Roles"
    if exp_cat == "ELIGIBILITY_UNKNOWN":
        if "empty" in r_lower or "null" in r_lower or "missing" in r_lower or "tbd" in r_lower or "not specified" in r_lower:
            return "Missing Location Information"
        return "Ambiguous Remote Eligibility"
    return "Other"


def _diagnose_discrepancy(
    desc: str,
    location: str,
    evidence: List[str],
    exp_act: str,
    pred_act: str,
    exp_cat: str,
    pred_cat: str,
) -> Dict[str, str]:
    """Diagnose the root cause rule or regex gap without modifying classifier."""
    full = f"{location}\n{desc}".lower()

    if pred_act in ["CONFIRMED_ELIGIBLE", "RELOCATION_PATHWAY"] and exp_act in ["INELIGIBLE", "PENDING_LOCATION_VERIFICATION"]:
        # False Positive
        return {
            "responsible_rule": f"Rule triggered actionable status ({pred_act}) based on evidence {evidence}, failing to detect negative constraint.",
            "recommended_correction": "Introduce stricter boundary checking or add specific negative exclusion regex to _RESTRICTION_PATTERNS."
        }
    elif pred_act == "INELIGIBLE" and exp_act in ["CONFIRMED_ELIGIBLE", "RELOCATION_PATHWAY"]:
        # False Negative
        return {
            "responsible_rule": f"Hard restriction rule triggered unexpectedly on evidence {evidence}.",
            "recommended_correction": "Examine if general restriction regex over-matched positive or non-restricting phrasing."
        }
    elif pred_act == "PENDING_LOCATION_VERIFICATION" and exp_act != "PENDING_LOCATION_VERIFICATION":
        # False Hold
        return {
            "responsible_rule": "Fallback to ELIGIBILITY_UNKNOWN because no positive or negative regex triggered.",
            "recommended_correction": "Add pattern to recognize this specific geographic indicator."
        }
    else:
        return {
            "responsible_rule": f"Category mismatch: expected {exp_cat}, got {pred_cat}.",
            "recommended_correction": "Align category resolution precedence in decision tree."
        }


def _generate_markdown_report(report: Dict[str, Any]):
    md_lines = [
        "# Job Hunter v2.3 — 100-Job Eligibility Benchmark Audit Report",
        "",
        "## Executive Summary",
        "",
        f"- **Total Dataset Samples:** {report['total_cases']}",
        f"- **Exact Actionability Matches:** {report['exact_match_count']}/{report['total_cases']} ({report['exact_match_accuracy_pct']}%)",
        f"- **Binary Actionability Accuracy:** {report['binary_actionable_accuracy_pct']}%",
        f"- **Precision:** {report['precision_pct']}%",
        f"- **Recall:** {report['recall_pct']}%",
        f"- **F1 Score:** {report['f1_score']}",
        f"- **CRITICAL False Positives (Unsafe Classifications):** **{report['false_positives']}**",
        f"- **False Negatives (Missed Opportunities):** **{report['false_negatives']}**",
        "",
        "## 1. Safety Gate Verdict",
        "",
    ]

    if report["false_positives"] == 0:
        md_lines.append("> [!IMPORTANT]\n> **PASSED CRITICAL SAFETY GATE (0 False Positives)**: Zero ineligible or ambiguous postings were classified as actionable. No unauthorized application or CV generation can be triggered.")
    else:
        md_lines.append(f"> [!CAUTION]\n> **FAILED SAFETY GATE**: {report['false_positives']} False Positives detected! Review the detailed error analysis below.")

    md_lines.extend([
        "",
        "## 2. 4x4 Actionability Confusion Matrix",
        "",
        "| Ground Truth \\ Predicted | CONFIRMED_ELIGIBLE | RELOCATION_PATHWAY | PENDING_LOCATION_VERIFICATION (HOLD) | INELIGIBLE |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])

    matrix = report["confusion_matrix"]
    for row_name in ["CONFIRMED_ELIGIBLE", "RELOCATION_PATHWAY", "PENDING_LOCATION_VERIFICATION", "INELIGIBLE"]:
        r = matrix.get(row_name, {})
        md_lines.append(
            f"| **{row_name}** | {r.get('CONFIRMED_ELIGIBLE', 0)} | {r.get('RELOCATION_PATHWAY', 0)} | {r.get('PENDING_LOCATION_VERIFICATION', 0)} | {r.get('INELIGIBLE', 0)} |"
        )

    md_lines.extend([
        "",
        "## 3. Category-Level Performance Metrics",
        "",
        "| Category Group | Total | Exact Correct | Precision | Recall | F1 | False Positives | False Negatives | Held for Verification |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    for grp, m in report["category_metrics"].items():
        md_lines.append(
            f"| **{grp}** | {m['total']} | {m['correct']} ({m['accuracy_pct']}%) | {m['precision_pct']}% | {m['recall_pct']}% | {m['f1_score']} | **{m['false_positives']}** | {m['false_negatives']} | {m['held_for_verification']} |"
        )

    if report["misclassified_cases"]:
        md_lines.extend([
            "",
            "## 4. Misclassified Cases & Error Analysis",
            "",
            "| ID | Title | Group | Expected | Predicted | Responsible Rule / Gap | Recommended Correction |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for mc in report["misclassified_cases"]:
            md_lines.append(
                f"| `{mc['id']}` | {mc['title']} | {mc['group']} | `{mc['expected_actionability']}` | `{mc['predicted_actionability']}` | {mc['responsible_rule_or_gap']} | {mc['recommended_correction']} |"
            )

    out_md = Path("benchmarks/eligibility/BENCHMARK_REPORT.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")


if __name__ == "__main__":
    report = evaluate_dataset()
    print("=" * 70)
    print("JOB HUNTER v2.3 — 100-JOB ELIGIBILITY BENCHMARK EVALUATION")
    print("=" * 70)
    print(f"Total Cases Evaluated:       {report['total_cases']}")
    print(f"Exact Actionability Matches: {report['exact_match_count']}/{report['total_cases']} ({report['exact_match_accuracy_pct']}%)")
    print(f"Binary Actionability Acc:    {report['binary_actionable_accuracy_pct']}%")
    print(f"Precision:                   {report['precision_pct']}%")
    print(f"Recall:                      {report['recall_pct']}%")
    print(f"F1 Score:                    {report['f1_score']}")
    print(f"CRITICAL False Positives:    {report['false_positives']} (Safety Failures)")
    print(f"False Negatives:             {report['false_negatives']} (Missed Opportunities)")
    print("=" * 70)
    if report["false_positives"] > 0:
        print("SAFETY AUDIT: FAILED (False positives detected)")
        sys.exit(1)
    else:
        print("SAFETY AUDIT: PASSED (Zero false positives)")
        sys.exit(0)
