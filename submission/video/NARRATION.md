# Narration script

**(0:00) Title.** "This is Rusted Recall — change-impact intelligence and
automated recall for generative media."

**(0:15) Source of truth.** "Brands reuse one package, claim, or licensed face
across hundreds of assets. Here's LumaLeaf sparkling water. Its on-pack claim is
changing from '24-Hour Vitality' to 'Daily Botanical Blend'."

**(0:35) Assets.** "Every asset we ingest gets a real SHA-256 and perceptual
hash, and the original is stored immutably in Backblaze B2 — we never overwrite
it."

**(0:55) Create recall.** "We declare the change as a recall: the old source
version, and the new one."

**(1:15) Impact map.** "Rusted Recall traverses the dependency graph from the
changed source and finds everything connected to it."

**(1:45) Review.** "Impact is explainable. The master pack is directly affected —
it explicitly declares this source. The recruiting poster is safe — no
dependency. You see the exact weighted components and the reason for every
score, not a black box."

**(2:10) Repair.** "Approved assets are repaired through the Genblaze and GMI
Cloud pipeline as durable jobs. The output is validated and stored as a new
immutable version with a manifest — the original stays intact."

**(2:35) Report.** "The whole recall exports as an auditable report — JSON, CSV,
HTML, or PDF — with an append-only timeline and integrity hashes."

**(2:55) Close.** "Every visible result traces to a real B2 object, a real
provider call, and a real audit event. That's Rusted Recall."
