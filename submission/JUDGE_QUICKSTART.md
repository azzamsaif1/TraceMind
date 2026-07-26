# Judge quickstart

**Fastest path (no setup):** open the hosted URL (added by the owner) and browse the public
LumaLeaf demo — no login, no password wall.

**Local (5 minutes):**

```bash
cp .env.example .env
docker compose up --build
# open http://localhost:8000
```

## What to look at

1. **Overview** (`/`) — the seeded LumaLeaf recall (claim change: "24-Hour Vitality" →
   "Daily Botanical Blend").
2. Open the recall → **Impact Map**: which assets are affected and how strongly.
3. **Technical Evidence** (`/recalls/{id}/evidence`): the ChangeSet, per-asset causal
   explanations, and the minimal repair plan with **operations avoided**.
4. **Repair Operations** + **Before/After**: real repairs (if provider creds are set) or an
   honest disabled state (if not) — never fabricated.
5. **Audit Report**: download JSON/CSV/HTML/PDF.
6. Create an account at `/signup` to confirm you get an isolated organisation/workspace.

See `submission/JUDGING_EVIDENCE.md` for how each judging criterion is satisfied.
