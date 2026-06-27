import hashlib
from PIL import Image
import imagehash

def calculate_sha256(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256.update(block)
    return sha256.hexdigest()

def calculate_perceptual_hash(file_path):
    img = Image.open(file_path)
    return str(imagehash.phash(img))
