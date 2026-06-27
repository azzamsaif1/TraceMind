import os
import b2sdk.v2 as b2
from dotenv import load_dotenv

load_dotenv()

B2_KEY_ID = os.getenv("B2_KEY_ID")
B2_APP_KEY = os.getenv("B2_APP_KEY")
B2_BUCKET_NAME = os.getenv("B2_BUCKET_NAME")

def get_b2_client():
    info = b2.InMemoryAccountInfo()
    b2_api = b2.B2Api(info)
    b2_api.authorize_account("production", B2_KEY_ID, B2_APP_KEY)
    return b2_api

def upload_to_b2(local_path, remote_name):
    b2_api = get_b2_client()
    bucket = b2_api.get_bucket_by_name(B2_BUCKET_NAME)
    uploaded = bucket.upload_local_file(local_file=local_path, file_name=remote_name)
    # The returned object is a FileVersion, which has file_name and file_id
    return uploaded.file_name   # we only need the name

def download_from_b2(remote_name, local_path):
    b2_api = get_b2_client()
    bucket = b2_api.get_bucket_by_name(B2_BUCKET_NAME)
    bucket.download_file_by_name(remote_name, local_path)

def get_public_url(remote_name):
    return f"https://{B2_BUCKET_NAME}.s3.us-west-000.backblazeb2.com/{remote_name}"
