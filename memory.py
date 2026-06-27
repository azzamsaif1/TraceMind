import json
import tempfile
from utils import get_b2_client, B2_BUCKET_NAME, download_from_b2

DECISIONS_PREFIX = "decisions/"

def list_all_decisions():
    b2_api = get_b2_client()
    bucket = b2_api.get_bucket_by_name(B2_BUCKET_NAME)
    decisions = []
    for file_info, _ in bucket.ls(prefix=DECISIONS_PREFIX):
        decisions.append(file_info.file_name)
    return decisions

def get_decision(decision_id):
    remote_name = f"{DECISIONS_PREFIX}{decision_id}.json"
    with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp:
        tmp_path = tmp.name
    try:
        download_from_b2(remote_name, tmp_path)
        with open(tmp_path, 'r') as f:
            return json.load(f)
    except Exception:
        return None
