import streamlit as st
from memory import list_all_decisions, get_decision

def show_failure_mode():
    st.subheader("❌ Failure Mode – Root Cause Analysis")
    decisions = list_all_decisions()
    if not decisions:
        st.info("No decisions to analyze.")
        return
    failures = []
    for fname in decisions:
        decision_id = fname.split('/')[-1].replace('.json', '')
        dec = get_decision(decision_id)
        if dec and dec.get("status") == "failed":
            failures.append(dec)
    if not failures:
        st.success("No failures found. All decisions succeeded!")
    else:
        for f in failures:
            st.write(f"**ID:** {f.get('decision_id')}")
            st.write(f"**Error:** {f.get('error')}")
            st.write("---")
