# Shot list

Pre-roll setup (off-camera):
- `python -m rusted_recall.demo.lumaleaf`
- `uvicorn rusted_recall.web.app:app`
- Browser at 1280×800, dark theme, zoom 100%.

| Shot | Action to capture | Duration |
| --- | --- | --- |
| S1 | Title card (static) | 3s |
| S2 | Command Center: stats cards + recall row | 8s |
| S3 | Source of Truth: expand the two claim versions | 12s |
| S4 | Asset Registry: scroll showing hashes + previews | 12s |
| S5 | Create Recall: pick item, old/new version, reason, submit | 18s |
| S6 | Recall detail: impact map renders (let edges draw) | 15s |
| S7 | Review Queue: hover a row; show reasons list | 20s |
| S8 | Click Run repairs; capture job status polling | 20s |
| S9 | Before/After gallery: before vs after + manifest link | 12s |
| S10 | Audit Report: click JSON then PDF download | 12s |
| S11 | Diagnostics: weights + thresholds + provider state | 8s |
| S12 | Close card | 4s |

If no live credentials: replace S8–S9 with the honesty banner ("Repairs
disabled — no provider configured") and a voiceover explaining no fake output is
shown.
