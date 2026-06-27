import streamlit as st

from memory import list_all_decisions, get_decision
from feedback_engine import get_global_feedback_engine


def show_failure_mode():
    """
    Displays root cause analysis of system failures.
    """

    st.subheader("❌ Failure Mode – Root Cause Analysis")

    # System-wide failure patterns
    engine = get_global_feedback_engine()
    failures = engine.failure_profiles

    if failures:
        st.write("**System-Wide Failure Patterns:**")
        for key, count in failures.items():
            st.write(f"- {key}: {count} occurrences")
    else:
        st.info("No failure patterns detected yet. Generate more decisions to train the system.")

    # Analyze stored decisions
    decisions = list_all_decisions()

    if not decisions:
        st.caption("No decisions to analyze. Generate some images first.")
        return

    failed_entries = []

    for fname in decisions:
        decision_id = fname.split('/')[-1].replace('.json', '')
        dec = get_decision(decision_id)

        if dec and dec.get("status") == "failure":
            failed_entries.append(dec)

    # Display failed cases
    if failed_entries:
        st.write("**Failed Decisions:**")

        for f in failed_entries:
            st.write(f"**ID:** {f.get('decision_id', 'Unknown')[:8]}")
            st.write(f"**Score:** {f.get('score', 0)}")
            st.write(
                f"**Reasons:** {', '.join(f.get('evaluation_reasons', ['unknown']))}"
            )
            st.write("---")
    else:
        st.success("🎉 No failed decisions found! All generations succeeded.")
