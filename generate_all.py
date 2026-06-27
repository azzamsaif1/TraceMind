import requests
import json
import os
import re
import time

API_URL = "https://api.us-west-2.modal.direct/v1/chat/completions"
API_KEY = "modalresearch_HJhsDslmr7YVYixsmIJ2ZydGmZNnfdBnPexdMb-0nHvw"
MODEL = "zai-org/GLM-5.1-FP8"

def ask_ai(prompt):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    data = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 4000}
    response = requests.post(API_URL, headers=headers, json=data)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

full_prompt = """
You are an expert Python developer. Write the complete code for the "Trusted Decision OS" project, which uses:
- Backblaze B2 for storage (b2sdk)
- Genblaze SDK with S3StorageBackend (genblaze-s3)
- GMI Cloud as provider (genblaze-gmicloud) or OpenAI (genblaze-openai)
- Streamlit for UI
- imagehash and Pillow for perceptual hashing

The project structure:
- orchestrator.py: run_decision() using Genblaze Pipeline with S3 sink, returns dict with decision_id, image_url, sha256, perceptual_hash, manifest, etc.
- provenance.py: save_manifest() and get_manifest() for B2.
- verification.py: SHA-256, perceptual hash, verify functions.
- memory.py: list_all_decisions(), get_decision(), save_decision_metadata().
- utils.py: B2 upload/download/public URL functions.
- modes/__init__.py (empty)
- modes/memory_mode.py: show_memory_mode() Streamlit function.
- modes/failure_mode.py: show_failure_mode().
- modes/opportunity_mode.py: show_opportunity_mode().
- app.py: main Streamlit app with sidebar navigation.
- README.md: comprehensive documentation.

Write each file as complete, runnable code. Use os.getenv and python-dotenv. No placeholders.

**Format your response exactly like this:**
## FILE: filename.py
```python
# code
```

## FILE: another.py
```python
# code
```
... and so on. Start with orchestrator.py.
"""

print("Sending request to GLM-5.1 (this may take up to 60 seconds)...")
try:
    response_text = ask_ai(full_prompt)
except Exception as e:
    print(f"Error: {e}")
    exit(1)

# Save raw response for debugging
with open("generated_response.txt", "w") as f:
    f.write(response_text)

pattern = r"## FILE:\s*([^\n]+)\s*\n```(?:python)?\s*\n(.*?)\n```"
matches = re.findall(pattern, response_text, re.DOTALL)

if not matches:
    pattern2 = r"## FILE:\s*([^\n]+)\s*\n(.*?)(?=\n## FILE:|$)"
    matches = re.findall(pattern2, response_text, re.DOTALL)

if not matches:
    print("Could not parse any file blocks. Full response saved to generated_response.txt. Please split manually.")
    exit(1)

os.makedirs("modes", exist_ok=True)

for filename, content in matches:
    filename = filename.strip()
    content = content.strip()
    dirname = os.path.dirname(filename)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(filename, "w") as f:
        f.write(content)
    print(f"\\u2705 Created {filename}")

print("\n\\u2705 All files generated. Now set up your .env with real keys, install dependencies, and run streamlit.")