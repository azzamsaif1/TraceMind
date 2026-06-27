import streamlit as st
from memory import list_all_decisions, get_decision

def show_memory_mode():
    st.subheader("📚 Memory – Past Decisions")
    decisions = list_all_decisions()
    if not decisions:
        st.info("No decisions recorded yet.")
        return
    data = []
    for fname in decisions:
        decision_id = fname.split('/')[-1].replace('.json', '')
        dec = get_decision(decision_id)
        if dec:
            data.append({
                "ID": decision_id,
                "Prompt": dec.get("prompt", "")[:50],
                "Model": dec.get("model", ""),
                "Timestamp": dec.get("timestamp", ""),
                "Image URL": dec.get("image_url", "")
            })
    st.table(data)
