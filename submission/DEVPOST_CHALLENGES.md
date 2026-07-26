# Challenges we ran into

- **Honesty under missing credentials.** The hardest design constraint was refusing to fake
  anything. We built explicit disabled/failed states so the product is fully demonstrable
  without provider keys, yet never pretends a repair happened.
- **Change-aware propagation.** Naively traversing the whole graph over-reports. Encoding
  which edge types each operation can propagate through (text vs. visual) was key to precision.
- **Minimal repair math.** Distinguishing deterministic children from assets that truly need
  regeneration — and proving the savings — required modelling derivation methods explicitly.
- **Inherited security debt.** The original prototype had committed secrets and fabricated
  output; we remediated the files, documented the git-history exposure, and rebuilt the core.
