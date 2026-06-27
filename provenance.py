import json
import tempfile
from utils import upload_to_b2, download_from_b2

MANIFEST_PREFIX = "manifests/"

def save_manifest(decision_id, manifest_data):
    json_str = json.dumps(manifest_data, indent=2)
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
        tmp.write(json_str)
        tmp_path = tmp.name
    remote_name = f"{MANIFEST_PREFIX}{decision_id}.json"
    upload_to_b2(tmp_path, remote_name)
    return remote_name

def get_manifest(decision_id):
    remote_name = f"{MANIFEST_PREFIX}{decision_id}.json"
    with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp:
        tmp_path = tmp.name
    try:
        download_from_b2(remote_name, tmp_path)
        with open(tmp_path, 'r') as f:
            return json.load(f)
    except Exception:
        return None
