import streamlit as st
from feedback_engine import get_global_feedback_engine

def show_opportunity_mode():
    """
    Displays system-generated improvement opportunities based on failure patterns.
    """
    st.subheader("💡 Dynamic Opportunities (System-Driven)")

    engine = get_global_feedback_engine()
    failures = engine.failure_profiles

    if not failures:
        st.info("✨ System is performing optimally. No failures detected. Keep generating!")
        st.write("Try exploring more complex prompts with detailed lighting and composition.")
        return

    st.write(
        "Based on the system's failure patterns, here are the **priority improvement opportunities**:"
    )

    # Map failure patterns to actionable improvement guidance
    opportunity_map = {
        "too_short": "📝 **Expand Prompt Depth**: Your prompts are too short. Add at least 3 descriptive sentences.",
        "no_lighting": "💡 **Add Lighting Context**: Specify time of day or lighting source (e.g., 'golden hour', 'neon glow').",
        "no_style": "🎨 **Define Artistic Style**: Choose a style (e.g., 'cinematic', 'vintage', 'cyberpunk', 'watercolor').",
        "no_subject": "🧩 **Clarify Main Subject**: Ensure the main subject is clearly defined (e.g., 'a cyberpunk samurai' instead of just 'samurai')."
    }

    for key, count in failures.most_common(3):
        if key in opportunity_map:
            st.markdown(f"- **{opportunity_map[key]}** (occurred {count} times)")
            st.progress(
                min(count / 10, 1.0),
                text=f"Severity: {count} occurrences"
            )

    st.divider()
    st.caption(
        "🔄 The system will automatically apply these improvements in future generations via Adaptive Prompting."
    )
