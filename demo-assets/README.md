# Demo assets — LumaLeaf Botanical Sparkling Water

## Provenance

The LumaLeaf campaign is **fictional**. All demo images are generated
**procedurally at seed time** by `rusted_recall/demo/lumaleaf.py` using Pillow
(solid shapes + text). There are **no third-party images, logos, fonts beyond
Pillow's built-in default, photographs, faces, or voices** in this dataset.

This keeps licensing clean: nothing here is copied from the web or any brand.
"LumaLeaf" and the claims "24-Hour Vitality" / "Daily Botanical Blend" are
invented for demonstration.

## What the seed creates

Running the seed drives the **same production ingestion + analysis services**
used by the web app (it does not insert graph or impact rows directly):

- One source-of-truth item (the product package) with two versions:
  - v1 claim **"24-Hour Vitality"**
  - v2 claim **"Daily Botanical Blend"** (the change that triggers the recall)
- Campaign assets: master pack render, hero advertisement, square social post,
  vertical story, a cropped hero used as an email header (a derivative child),
  and an unrelated "We're Hiring" corporate poster (should classify as *safe*).
- A recall event for the claim change, analysed into per-asset impact.

## Reproduce

```bash
export APP_ENV=development STORAGE_BACKEND=local \
       DATABASE_URL="sqlite:///./rusted_recall.db"
python -m rusted_recall.demo.lumaleaf
```

The command is idempotent per database: it no-ops if the `lumaleaf-botanical`
workspace already exists.

## Repairs in the demo

Repairs call the real Genblaze/GMI pipeline. Without `GMICLOUD_API_KEY` the
repair action is **disabled** in the UI and jobs are recorded as failed with a
clear reason — no fabricated "after" images are shown. Provide a real key to
produce genuine repaired outputs.
