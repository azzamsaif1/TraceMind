import requests
import json
import os

API_URL = "https://api.us-west-2.modal.direct/v1/chat/completions"
API_KEY = "modalresearch_HJhsDslmr7YVYixsmIJ2ZydGmZNfdBnPExdMb-0nHvw"
MODEL = "zai-org/GLM-5.1-FP8"

def ask_ai(prompt):
    """Send a prompt to GLM-5.1 and return the response text."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000
    }
    response = requests.post(API_URL, headers=headers, json=data)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# File generation prompts (complete specifications for each file)
files_to_generate = {
    ".env.example": """B2_KEY_ID=your_key_id
B2_APP_KEY=your_app_key
B2_BUCKET_NAME=your_bucket
GMICLOUD_API_KEY=your_gmi_key
OPENAI_API_KEY=your_openai_key""",

    "requirements.txt": """streamlit
genblaze-core
genblaze-gmicloud
genblaze-openai
genblaze-s3
b2sdk
python-dotenv
Pillow
imagehash
requests
sqlalchemy
pytest
""",

    # For more complex files, we'll ask the AI to generate each one.
}

# First, create simple files directly
for filename, content in files_to_generate.items():
    with open(filename, "w") as f:
        f.write(content)
    print(f"Created {filename}")

# Now ask the AI to generate the main Python files
main_files = [
    ("orchestrator.py", "Write complete Python code for orchestrator.py that uses Genblaze pipelines with Backblaze B2, GMI Cloud, etc. Include run_decision function returning dict with image_url, sha256, perceptual_hash, manifest, etc. Write full implementation with imports and error handling."),
    ("provenance.py", "Write complete Python code for provenance.py with functions to save and retrieve manifest from B2."),
    ("verification.py", "Write complete Python code for verification.py with functions for SHA-256, perceptual hash, and verification against stored manifest."),
    ("memory.py", "Write complete Python code for memory.py with functions to list all decisions and get decision metadata from B2."),
    ("utils.py", "Write complete Python code for utils.py with B2 upload, download, and public URL functions using b2sdk."),
    ("modes/__init__.py", "Empty init file."),
    ("modes/memory_mode.py", "Write Streamlit function show_memory_mode() that displays all decisions from B2 in a table."),
    ("modes/failure_mode.py", "Write Streamlit function show_failure_mode() that shows failure analysis."),
    ("modes/opportunity_mode.py", "Write Streamlit function show_opportunity_mode() that scrapes Reddit and shows opportunities."),
    ("app.py", "Write complete Streamlit app with sidebar navigation and tabs: Home, Make Decision, Verify, Memory, Failure Analysis, Opportunities. Integrate all functions."),
    ("README.md", "Write a comprehensive README for the Trusted Decision OS project, explaining the problem, solution, setup, usage, and hackathon alignment."),
]

os.makedirs("modes", exist_ok=True)

for filename, prompt_suffix in main_files:
    print(f"Generating {filename}...")
    full_prompt = f"You are an expert Python developer. Generate the complete code for {filename} as part of the Trusted Decision OS project. The project uses: Backblaze B2, Genblaze (with S3 sink), GMI Cloud, Streamlit, imagehash, etc. Provide only the code without extra explanation. {prompt_suffix}"
    try:
        code = ask_ai(full_prompt)
        with open(filename, "w") as f:
            f.write(code)
        print(f"✅ Created {filename}")
    except Exception as e:
        print(f"❌ Failed to generate {filename}: {e}")

print("All files generated. You may need to adjust imports and configurations.")
