"""
Regression and safety gate test executing the 100-job eligibility benchmark.
Guarantees 0 False Eligible classifications across all synthetic and real-world test cases.
"""

from benchmarks.eligibility.runner import run_benchmark


def test_100_job_eligibility_benchmark_safety_gate():
    """
    Execute the 100-job eligibility benchmark.
    Assert zero False Eligible predictions (critical safety constraint).
    """
    summary = run_benchmark()

    # Safety Invariant: NEVER classify an ineligible or unverified role as eligible
    assert summary["false_eligible_count"] == 0, (
        f"CRITICAL SAFETY VIOLATION: {summary['false_eligible_count']} false eligible jobs detected: "
        f"{summary['false_eligible_details']}"
    )

    # Invariant: Accuracy across benchmark must be >= 95%
    assert summary["accuracy_pct"] >= 95.0, (
        f"Benchmark accuracy dropped to {summary['accuracy_pct']}%. Expected >= 95%."
    )

    # Invariant: Ambiguous cases must remain held
    assert summary["group_metrics"]["Ambiguous / Needs Verification"]["held"] == 8
