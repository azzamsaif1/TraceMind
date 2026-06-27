import os
import uuid
import json
from datetime import datetime
from PIL import Image, ImageDraw
from dotenv import load_dotenv

from utils import upload_to_b2, get_public_url
from verification import calculate_sha256, calculate_perceptual_hash
from provenance import save_manifest
from feedback_engine import get_global_feedback_engine

load_dotenv()

B2_BUCKET_NAME = os.getenv("B2_BUCKET_NAME")
feedback_engine = get_global_feedback_engine()


def run_decision(base_prompt, model="gmi/seedream-5.0-lite"):
    """
    Full decision pipeline:
    - Applies adaptive system wisdom
    - Generates image (mock implementation)
    - Uploads artifacts to B2 storage
    - Computes verification hashes
    - Evaluates quality
    - Stores provenance safely
    """

    # 1. Retrieve adaptive wisdom
    wisdom = feedback_engine.get_adaptive_wisdom()

    # 2. Build enhanced prompt
    enhanced_prompt = base_prompt + ("\n\n" + wisdom if wisdom else "")

    decision_id = str(uuid.uuid4())

    # 3. Mock image generation (replace with real model later)
    img = Image.new('RGB', (512, 512), color=(73, 109, 137))
    draw = ImageDraw.Draw(img)

    draw.text((10, 10), f"ID: {decision_id[:8]}", fill=(255, 255, 255))
    draw.text((10, 30), f"Wisdom: {wisdom is not None}", fill=(200, 200, 0))
    draw.text((10, 50), enhanced_prompt[:100], fill=(255, 255, 255))

    local_path = f"/tmp/{decision_id}.png"
    img.save(local_path)

    # 4. Upload image
    remote_name = f"images/{decision_id}.png"
    upload_to_b2(local_path, remote_name)
    image_url = get_public_url(remote_name)

    # 5. Integrity hashes
    sha256 = calculate_sha256(local_path)
    phash = calculate_perceptual_hash(local_path)

    # 6. Raw decision object
    raw_decision = {
        "decision_id": decision_id,
        "prompt": enhanced_prompt,
        "model": model,
        "timestamp": datetime.utcnow().isoformat(),
        "image_url": image_url,
        "image_sha256": sha256,
        "perceptual_hash": phash
    }

    # 7. Evaluate decision
    evaluation = feedback_engine.evaluate_decision(raw_decision)

    # 8. Final manifest
    manifest = {
        **raw_decision,
        "score": evaluation["score"],
        "status": evaluation["status"],
        "evaluation_reasons": evaluation["reasons"],
        "original_prompt": base_prompt,
        "wisdom_used": wisdom if wisdom else None
    }

    # ===== Safe persistence layer =====

    # Save immutable manifest
    save_manifest(decision_id, manifest)

    # Write decision JSON safely
    json_path = f"/tmp/{decision_id}_data.json"

    with open(json_path, "w") as f:
        json.dump(manifest, f)
        f.flush()
        os.fsync(f.fileno())

    # Validate before upload
    if os.path.getsize(json_path) <= 0:
        raise RuntimeError("JSON file is empty after write operation!")

    upload_to_b2(json_path, f"decisions/{decision_id}.json")
    os.remove(json_path)

    return decision_id, image_url, manifest, evaluation["score"]
