"""Public task support excludes categories subtractable from source-wide audits."""

PUBLIC_AUDIT_POLICY = "recovery-task-eligibility-only"
PUBLIC_COUNTS = frozenset(
    {
        "eligible_resolved",
        "eligible_censored",
        "eligible_paired_wearable_day",
        "censor_bound_before_last_survey",
        "excluded_no_symptomatic_landmark",
        "excluded_no_current_score",
        "excluded_missing_current_score_value",
        "excluded_interval_not_after_landmark",
        "excluded_no_future_follow_up",
    }
)


def public_counts(audit: dict[str, int]) -> dict[str, int]:
    """Allowlist task-specific counts; new source categories stay private by default.

    Eligibility still correlates with source categories. Minimized counts plus
    existing source-wide audits leave residual test-total inferability, disclosed
    in each receipt. This boundary cannot restore historical blindness.
    """
    return {key: value for key, value in sorted(audit.items()) if key in PUBLIC_COUNTS}
