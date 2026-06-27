import streamlit as st
import requests

def show_opportunity_mode():
    st.subheader("💡 Opportunity Mode – Discover New Ideas")
    try:
        resp = requests.get("https://www.reddit.com/r/MachineLearning/hot.json?limit=5", headers={"User-Agent": "TrustedDecisionOS/1.0"})
        data = resp.json()
        posts = data['data']['children']
        for post in posts:
            p = post['data']
            st.write(f"**{p['title']}**")
            st.write(f"Score: {p['score']} | Comments: {p['num_comments']}")
            st.write(f"[Link]({p['url']})")
            st.write("---")
    except Exception as e:
        st.error(f"Could not fetch opportunities: {e}")
