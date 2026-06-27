import streamlit as st
from dotenv import load_dotenv
import os
from orchestrator import run_decision
from modes.memory_mode import show_memory_mode
from modes.failure_mode import show_failure_mode
from modes.opportunity_mode import show_opportunity_mode

load_dotenv()

st.set_page_config(page_title="Trusted Decision OS", layout="wide")
st.title("🧠 Trusted Decision OS – Single Decision Loop")

menu = st.sidebar.radio("Navigation", ["Generate", "Memory", "Failures", "Opportunities"])

if menu == "Generate":
    st.subheader("⚡ Generate a new decision")
    prompt = st.text_area("Enter your prompt", "A futuristic cityscape at sunset")
    model = st.selectbox("Model", ["gmi/seedream-5.0-lite", "openai/dall-e-3"])
    if st.button("Generate"):
        with st.spinner("Generating..."):
            try:
                decision_id, image_url, manifest = run_decision(prompt, model)
                st.success(f"Decision generated! ID: {decision_id}")
                st.image(image_url, caption="Generated Image")
                st.json(manifest)
            except Exception as e:
                st.error(f"Error: {e}")

elif menu == "Memory":
    show_memory_mode()

elif menu == "Failures":
    show_failure_mode()

elif menu == "Opportunities":
    show_opportunity_mode()
