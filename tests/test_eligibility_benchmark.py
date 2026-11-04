"""
Regression and safety gate test executing the independent 100-job eligibility benchmark.
Guarantees 0 False Positive safety failures and verifies fail-closed behavior on phrasing edge cases.
"""

from benchmarks.eligibility.runner import evaluate_dataset
from src.evaluators.eligibility import classify_eligibility, ActionabilityState


def test_100_job_eligibility_benchmark_safety_gate():
    """
    Execute the independent 100-job eligibility benchmark.
    Assert zero False Positives (critical safety constraint).
    """
    report = evaluate_dataset()

    # Safety Invariant: NEVER classify an ineligible or unverified role as eligible
    assert report["false_positives"] == 0, (
        f"CRITICAL SAFETY VIOLATION: {report['false_positives']} false positives detected: "
        f"{report['false_positives_details']}"
    )

    # Invariant: Accuracy across benchmark must be >= 95%
    assert report["exact_match_accuracy_pct"] >= 95.0, (
        f"Benchmark accuracy dropped to {report['exact_match_accuracy_pct']}%. Expected >= 95%."
    )

    # Invariant: Binary Actionable Accuracy must be 100%
    assert report["binary_actionable_accuracy_pct"] == 100.0


def test_benchmark_edge_cases_fail_closed_to_hold():
    """
    Verify that edge cases with unmodeled restriction phrasing (e.g., 'must be based in the US or Canada')
    fail safely to PENDING_LOCATION_VERIFICATION (HOLD) rather than producing an unsafe False Positive.
    """
    res1 = classify_eligibility(
        title="Junior AI Support Engineer",
        location_str="Remote",
        description="Remote. Mandatory overlap with US East Coast business hours (9am - 5pm EST). Must be based in the US or Canada.",
        is_remote=True,
    )
    # Must NOT be CONFIRMED_ELIGIBLE or RELOCATION_PATHWAY
    assert res1.actionability != ActionabilityState.CONFIRMED_ELIGIBLE
    assert res1.actionability != ActionabilityState.RELOCATION_PATHWAY
    assert not res1.can_apply_from_india
    # Safely held
    assert res1.actionability == ActionabilityState.PENDING_LOCATION_VERIFICATION

    res2 = classify_eligibility(
        title="Associate LLM Evaluator",
        location_str="Remote (PST Timezone)",
        description="Remote. Working hours strictly 9am - 5pm PST. Must reside in the US or Mexico.",
        is_remote=True,
    )
    assert res2.actionability != ActionabilityState.CONFIRMED_ELIGIBLE
    assert res2.actionability != ActionabilityState.RELOCATION_PATHWAY
    assert not res2.can_apply_from_india
    assert res2.actionability == ActionabilityState.PENDING_LOCATION_VERIFICATION
