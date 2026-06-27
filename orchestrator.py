import os
import uuid
import json
import tempfile
from datetime import datetime
from PIL import Image, ImageDraw
from dotenv import load_dotenv
from utils import upload_to_b2, get_public_url
from verification import calculate_sha256, calculate_perceptual_hash
from provenance import save_manifest

load_dotenv()

B2_BUCKET_NAME = os.getenv("B2_BUCKET_NAME")

def run_decision(prompt, model="dummy"):
    """
    Generate a dummy image locally (colored square with prompt text),
    upload to B2, compute hashes, and store manifest.
    """
    decision_id = str(uuid.uuid4())
    
    # Create a simple image
    img = Image.new('RGB', (512, 512), color=(73, 109, 137))
    d = ImageDraw.Draw(img)
    d.text((10, 10), prompt[:50], fill=(255, 255, 255))
    
    # Save locally
    local_path = f"/tmp/{decision_id}.png"
    img.save(local_path)
    
    # Upload to B2
    remote_name = f"images/{decision_id}.png"
    upload_to_b2(local_path, remote_name)
    image_url = get_public_url(remote_name)
    
    # Compute hashes
    sha256 = calculate_sha256(local_path)
    phash = calculate_perceptual_hash(local_path)
    
    # Build manifest
    manifest = {
        "decision_id": decision_id,
        "prompt": prompt,
        "model": model,
        "timestamp": datetime.utcnow().isoformat(),
        "image_url": image_url,
        "image_sha256": sha256,
        "perceptual_hash": phash,
        "status": "success"
    }
    
    # Save manifest to B2
    save_manifest(decision_id, manifest)
    
    # Also save full decision as JSON (for memory)
    decision_data = manifest.copy()
    # Remove image_data to keep it light
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
        json.dump(decision_data, tmp)
        tmp_path = tmp.name
    upload_to_b2(tmp_path, f"decisions/{decision_id}.json")
    
    return decision_id, image_url, manifest
