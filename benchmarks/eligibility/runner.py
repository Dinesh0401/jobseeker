"""
Benchmark evaluation harness for Job Hunter v2.2 eligibility classification.
Evaluates 100 benchmark job postings and audits for False Eligible safety defects.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.evaluators.eligibility import classify_eligibility, ActionabilityState, EligibilityCategory


def run_benchmark(cases_path: str = "benchmarks/eligibility/benchmark_cases.json") -> Dict[str, Any]:
    with open(cases_path, "r", encoding="utf-8") as f:
        cases: List[Dict[str, Any]] = json.load(f)

    results = []
    false_eligible = []
    false_ineligible = []
    false_holds = []
    correct_cases = 0

    group_stats = defaultdict(lambda: {
        "total": 0,
        "correct": 0,
        "false_eligible": 0,
        "false_ineligible": 0,
        "held": 0,
    })

    confusion_matrix = defaultdict(lambda: defaultdict(int))

    for case in cases:
        c_id = case["id"]
        group = case["category_group"]
        expected_cat = case["expected_category"]
        expected_act = case["expected_actionability"]
        expected_india = case["expected_can_apply_from_india"]

        assessment = classify_eligibility(
            title=case["title"],
            location_str=case["location"],
            description=case["description"],
            is_remote=case.get("is_remote", False),
        )

        pred_cat = assessment.category.value
        pred_act = assessment.actionability.value
        pred_india = assessment.can_apply_from_india

        group_stats[group]["total"] += 1
        confusion_matrix[expected_act][pred_act] += 1

        is_cat_match = (pred_cat == expected_cat)
        is_act_match = (pred_act == expected_act)
        is_india_match = (pred_india == expected_india)

        case_passed = is_act_match and is_india_match

        # Critical Safety Gate Check: False Eligible
        # If ground truth was NOT eligible, but engine said CONFIRMED_ELIGIBLE or can_apply_from_india=True
        is_false_eligible = False
        if expected_act in ["INELIGIBLE", "PENDING_LOCATION_VERIFICATION"]:
            if pred_act in ["CONFIRMED_ELIGIBLE", "RELOCATION_PATHWAY"] or pred_india:
                is_false_eligible = True
                false_eligible.append({
                    "id": c_id,
                    "title": case["title"],
                    "group": group,
                    "expected_actionability": expected_act,
                    "predicted_actionability": pred_act,
                    "predicted_category": pred_cat,
                    "evidence": assessment.evidence,
                })
                group_stats[group]["false_eligible"] += 1

        # Opportunity Cost: False Ineligible
        # Ground truth was CONFIRMED_ELIGIBLE or RELOCATION_PATHWAY, but engine marked INELIGIBLE
        is_false_ineligible = False
        if expected_act in ["CONFIRMED_ELIGIBLE", "RELOCATION_PATHWAY"]:
            if pred_act == "INELIGIBLE":
                is_false_ineligible = True
                false_ineligible.append({
                    "id": c_id,
                    "title": case["title"],
                    "group": group,
                    "expected_actionability": expected_act,
                    "predicted_actionability": pred_act,
                    "predicted_category": pred_cat,
                    "evidence": assessment.evidence,
                })
                group_stats[group]["false_ineligible"] += 1

        if pred_act == "PENDING_LOCATION_VERIFICATION":
            group_stats[group]["held"] += 1
            if expected_act != "PENDING_LOCATION_VERIFICATION":
                false_holds.append({
                    "id": c_id,
                    "title": case["title"],
                    "group": group,
                    "expected_actionability": expected_act,
                    "predicted_actionability": pred_act,
                })

        if case_passed:
            correct_cases += 1
            group_stats[group]["correct"] += 1

        results.append({
            "id": c_id,
            "group": group,
            "title": case["title"],
            "expected_category": expected_cat,
            "predicted_category": pred_cat,
            "expected_actionability": expected_act,
            "predicted_actionability": pred_act,
            "expected_can_apply_from_india": expected_india,
            "predicted_can_apply_from_india": pred_india,
            "passed": case_passed,
            "is_false_eligible": is_false_eligible,
            "is_false_ineligible": is_false_ineligible,
            "evidence": assessment.evidence,
        })

    total_cases = len(cases)
    accuracy = (correct_cases / total_cases) * 100 if total_cases > 0 else 0.0

    summary = {
        "total_cases": total_cases,
        "correct_actionability_and_india": correct_cases,
        "accuracy_pct": round(accuracy, 2),
        "false_eligible_count": len(false_eligible),
        "false_ineligible_count": len(false_ineligible),
        "false_hold_count": len(false_holds),
        "false_eligible_details": false_eligible,
        "false_ineligible_details": false_ineligible,
        "false_hold_details": false_holds,
        "group_metrics": {k: dict(v) for k, v in group_stats.items()},
        "confusion_matrix": {k: dict(v) for k, v in confusion_matrix.items()},
    }

    # Save JSON Report
    report_json_path = Path("benchmarks/eligibility/benchmark_report.json")
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Save Markdown Report
    md_lines = [
        "# Job Hunter v2.2 — 100-Job Eligibility Benchmark Audit Report",
        "",
        f"- **Total Evaluated Cases:** {total_cases}",
        f"- **Overall Actionability Accuracy:** {summary['accuracy_pct']}% ({correct_cases}/{total_cases})",
        f"- **CRITICAL False Eligible Count (Safety Defects):** {len(false_eligible)}",
        f"- **False Ineligible Count (Missed Opportunities):** {len(false_ineligible)}",
        f"- **Cases Placed on Hold for Verification:** {sum(g['held'] for g in group_stats.values())}",
        "",
        "## 1. Safety Audit Verdict",
        "",
    ]

    if len(false_eligible) == 0:
        md_lines.append("> [!IMPORTANT]\n> **PASSED SAFETY GATE**: Zero false-eligible classifications detected across all 100 benchmark postings. No ineligible or ambiguous posting bypassed location gates.")
    else:
        md_lines.append(f"> [!CAUTION]\n> **FAILED SAFETY GATE**: {len(false_eligible)} false-eligible classifications detected! Ineligible postings would have reached application phases.")

    md_lines.extend([
        "",
        "## 2. Category Performance Breakdown",
        "",
        "| Category Group | Total Cases | Correct | False Eligible (Unsafe) | False Ineligible (Missed) | Held for Verification |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ])

    for grp, st in group_stats.items():
        md_lines.append(
            f"| **{grp}** | {st['total']} | {st['correct']} | **{st['false_eligible']}** | {st['false_ineligible']} | {st['held']} |"
        )

    md_lines.extend([
        "",
        "## 3. Actionability Confusion Matrix",
        "",
        "| Expected \\ Predicted | CONFIRMED_ELIGIBLE | RELOCATION_PATHWAY | PENDING_LOCATION_VERIFICATION | INELIGIBLE |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])

    for exp_act in ["CONFIRMED_ELIGIBLE", "RELOCATION_PATHWAY", "PENDING_LOCATION_VERIFICATION", "INELIGIBLE"]:
        row = confusion_matrix[exp_act]
        md_lines.append(
            f"| **{exp_act}** | {row['CONFIRMED_ELIGIBLE']} | {row['RELOCATION_PATHWAY']} | {row['PENDING_LOCATION_VERIFICATION']} | {row['INELIGIBLE']} |"
        )

    if false_eligible:
        md_lines.extend([
            "",
            "## 4. False Eligible Safety Defects Details",
            "",
            "| ID | Title | Group | Predicted Actionability | Evidence |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for fe in false_eligible:
            md_lines.append(f"| {fe['id']} | {fe['title']} | {fe['group']} | {fe['predicted_actionability']} | `{fe['evidence']}` |")

    md_report_path = Path("benchmarks/eligibility/BENCHMARK_REPORT.md")
    with open(md_report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    return summary


if __name__ == "__main__":
    summary = run_benchmark()
    print(f"Benchmark completed: {summary['correct_actionability_and_india']}/{summary['total_cases']} correct ({summary['accuracy_pct']}%)")
    print(f"CRITICAL False Eligible (Safety Defects): {summary['false_eligible_count']}")
    print(f"False Ineligible (Missed Opportunities): {summary['false_ineligible_count']}")
    if summary["false_eligible_count"] > 0:
        sys.exit(1)
    sys.exit(0)
