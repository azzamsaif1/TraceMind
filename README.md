# Trusted Decision OS

A full‑stack provenance system for AI‑generated media.  
Every generated image is stored with its SHA‑256 hash, perceptual hash, and a verifiable manifest on Backblaze B2.

## Features
- **Single Decision Loop**: Generate images, store with proof.
- **Memory**: List past decisions with details.
- **Failure Mode**: Analyse root causes of failed generations.
- **Opportunity Mode**: Discover new ideas from Reddit.

## Tech Stack
- Streamlit, Genblaze, Backblaze B2, GMI Cloud, Pillow, imagehash.

## Setup
1. Copy `.env.example` to `.env` and add your keys.
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `streamlit run app.py`

## Environment Variables
- `B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET_NAME`
- `GMICLOUD_API_KEY`

## Deployment
Deploy to Streamlit Cloud using the same environment variables.

## License
MIT
