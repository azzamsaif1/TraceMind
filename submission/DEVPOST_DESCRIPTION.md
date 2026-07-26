# Rusted Recall

**Change-impact intelligence and automated recall for generative media.**

Brands ship the same claim, logo, price, or licensed likeness across hundreds of derived
media assets. When the source of truth changes, finding and fixing every downstream asset
is manual, error-prone, and unauditable. Rusted Recall turns that into a tracked,
explainable, reversible workflow.

When a source-of-truth element changes, Rusted Recall:

1. models the change as a typed **ChangeSet**;
2. **propagates** it through a multimodal dependency graph, following only the relationships
   the change can actually travel along;
3. classifies every affected asset with an **explainable** weighted evidence score and a
   causal explanation of *why*;
4. computes a **Minimal Repair Plan** that repairs masters once and rebuilds deterministic
   crop/resize children instead of regenerating everything;
5. executes real repairs through Genblaze + GMI Cloud, storing each result as a new
   immutable version in Backblaze B2 with a manifest;
6. produces a complete, reconstructable **audit report** (JSON/CSV/HTML/PDF).

It is one application that is simultaneously a hackathon submission, a judge-facing product,
and a self-hostable multi-tenant SaaS. The LumaLeaf Botanical Sparkling Water campaign is
seeded through the exact production code path a real customer uses — nothing is faked, and
missing integrations fail honestly instead of fabricating results.
