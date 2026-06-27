import json
import os
import streamlit as st

from utils import get_b2_client, B2_BUCKET_NAME, download_from_b2

DECISIONS_PREFIX = "decisions/"


def list_all_decisions():
    """
    Return all decision files from B2 storage, including corrupted ones.
    """
    b2_api = get_b2_client()
    bucket = b2_api.get_bucket_by_name(B2_BUCKET_NAME)

    decisions = []

    try:
        for file_info, _ in bucket.ls(DECISIONS_PREFIX):
            decisions.append(file_info.file_name)

    except Exception as e:
        st.warning(f"Could not list B2 files: {e}")

    return decisions


def get_decision(decision_id):
    """
    Retrieve a decision from storage.
    Returns None if the file is missing, empty, or corrupted.
    """
    remote_name = f"{DECISIONS_PREFIX}{decision_id}.json"
    tmp_path = f"/tmp/{decision_id}.json"

    try:
        download_from_b2(remote_name, tmp_path)

        if os.path.getsize(tmp_path) == 0:
            os.remove(tmp_path)
            return None

        with open(tmp_path, 'r') as f:
            data = json.load(f)

        os.remove(tmp_path)
        return data

    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return None
