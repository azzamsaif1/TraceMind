import json
import os
from utils import upload_to_b2, download_from_b2

MANIFEST_PREFIX = "manifests/"

def save_manifest(decision_id, manifest_data):
    """
    Save a provenance manifest with guaranteed disk flush,
    then upload it to B2 storage.
    """
    json_str = json.dumps(manifest_data, indent=2)
    tmp_path = f"/tmp/manifest_{decision_id}.json"

    with open(tmp_path, 'w') as f:
        f.write(json_str)
        f.flush()
        os.fsync(f.fileno())  # ensure OS-level persistence

    remote_name = f"{MANIFEST_PREFIX}{decision_id}.json"
    upload_to_b2(tmp_path, remote_name)

    os.remove(tmp_path)
    return remote_name


def get_manifest(decision_id):
    """
    Retrieve a provenance manifest from B2 storage.
    Returns None if file is missing, corrupted, or invalid.
    """
    remote_name = f"{MANIFEST_PREFIX}{decision_id}.json"
    tmp_path = f"/tmp/manifest_get_{decision_id}.json"

    try:
        download_from_b2(remote_name, tmp_path)

        if os.path.getsize(tmp_path) == 0:
            raise ValueError("Empty manifest")

        with open(tmp_path, 'r') as f:
            data = json.load(f)

        os.remove(tmp_path)
        return data

    except Exception:
        return None
