# Recording checklist

Before recording:
- [ ] Fresh DB + storage (`rm rusted_recall.db`, clear local storage) then seed.
- [ ] Server running; `/healthz` and `/readyz` green.
- [ ] Browser 1280×800, dark theme, 100% zoom, no extensions/bookmarks bar.
- [ ] Decide mode: **live repairs** (real `GMICLOUD_API_KEY` + B2 set) or
      **honest-disabled** (narrate the disabled banner).
- [ ] If live: confirm `DEMO_MAX_REPAIRS_PER_RECALL` bounds cost.

During:
- [ ] Follow SHOT_LIST order; pause ~1s on each screen for legibility.
- [ ] Show at least one explainable score with its reasons.
- [ ] Show the original is preserved (before/after side by side).
- [ ] Trigger at least one real report download.

After:
- [ ] Trim to ≤ 3:00.
- [ ] Add captions from CAPTIONS.md.
- [ ] Export 1080p MP4 → `submission/video/rusted-recall.mp4`.
- [ ] Thumbnail → `submission/video/thumbnail.png`.
- [ ] Verify audio levels and that no secret values are visible on screen.

Human-only:
- [ ] Record the final screen capture (agent cannot capture system audio/video).
- [ ] Confirm the live Devpost deadline and submit.
