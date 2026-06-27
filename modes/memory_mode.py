import streamlit as st

from memory import list_all_decisions, get_decision


def show_memory_mode():
    """
    Displays historical decision memory from B2 storage.
    """

    st.subheader("📚 Memory – Past Decisions")

    decisions = list_all_decisions()

    if not decisions:
        st.info("No decision files found in B2. Generate some images!")
        return

    data = []
    valid_count = 0

    for fname in decisions:
        decision_id = fname.split('/')[-1].replace('.json', '')
        dec = get_decision(decision_id)

        if dec:
            valid_count += 1
            data.append({
                "ID": decision_id[:8],
                "Prompt": dec.get("prompt", "N/A")[:60],
                "Score": dec.get("score", "N/A"),
                "Model": dec.get("model", "N/A"),
                "Status": dec.get("status", "unknown")
            })
        else:
            st.caption(f"⏳ Decision {decision_id[:8]}... (loading or corrupted)")

    if data:
        st.dataframe(data, use_container_width=True)
        st.caption(
            f"✅ Showing {len(data)} valid decisions out of {len(decisions)} total files."
        )
    else:
        st.warning(
            f"⚠️ Found {len(decisions)} files but none could be loaded. Try generating a new decision."
        )
