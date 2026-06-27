import streamlit as st
from dotenv import load_dotenv
import os

from orchestrator import run_decision
from modes.memory_mode import show_memory_mode
from modes.failure_mode import show_failure_mode
from modes.opportunity_mode import show_opportunity_mode
from feedback_engine import get_global_feedback_engine

load_dotenv()

st.set_page_config(
    page_title="Trusted Decision OS v2.0 - Self Improving",
    layout="wide"
)

st.title("🧠 Trusted Decision OS – Self-Improving AI Loop")
st.caption("Dynamic Adaptive Prompting | Real-time Decision Scoring | Active Learning | Self-Healing System")

# Initialize feedback engine
feedback_engine = get_global_feedback_engine()

menu = st.sidebar.radio(
    "Navigation",
    ["Generate", "Memory", "Failures", "Opportunities"]
)

if menu == "Generate":
    st.subheader("⚡ Generate a new decision")

    # Show adaptive system wisdom if available
    wisdom = feedback_engine.get_adaptive_wisdom()
    if wisdom:
        with st.expander("🧠 Active Wisdom (Auto-Applied)", expanded=False):
            st.info(wisdom)
    else:
        st.caption("No historical wisdom yet. Generate a few runs to train the system.")

    base_prompt = st.text_area(
        "Enter your base prompt",
        "A futuristic cityscape at sunset"
    )

    model = st.selectbox(
        "Model",
        ["gmi/seedream-5.0-lite", "openai/dall-e-3"]
    )

    if st.button("Generate with AI Feedback"):
        with st.spinner("Generating and evaluating decision..."):
            try:
                decision_id, image_url, manifest, score = run_decision(base_prompt, model)

                col1, col2 = st.columns([2, 1])

                with col1:
                    st.success(f"Decision generated! ID: {decision_id}")
                    st.image(image_url, caption="Generated Image")

                with col2:
                    st.metric("Decision Score", f"{score:.2f}")

                    status_color = "green" if manifest["status"] == "success" else "red"
                    st.markdown(
                        f"**Status**: <span style='color:{status_color}'>{manifest['status'].upper()}</span>",
                        unsafe_allow_html=True
                    )

                    if manifest.get("wisdom_used"):
                        st.caption("✅ Adapted based on past failures")
                    else:
                        st.caption("No prior context adapted")

                    if manifest["evaluation_reasons"]:
                        st.write("**Feedback Reasons:**")
                        for r in manifest["evaluation_reasons"]:
                            st.write(f"- {r}")

                # Full manifest viewer
                with st.expander("📄 Full Verifiable Manifest"):
                    st.json(manifest)

            except Exception as e:
                st.error(f"Error: {e}")

elif menu == "Memory":
    show_memory_mode()

elif menu == "Failures":
    show_failure_mode()

elif menu == "Opportunities":
    show_opportunity_mode()
