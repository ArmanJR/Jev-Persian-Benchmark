# Dataset v1.0.0 review

The author completed a second pass over the emitted states, all 480 questions and
resolved gold labels before any live evaluation (2026-09-22 UTC). This was an
additional review by the same authoring model, not independent human annotation.
All labels were retained. The review checked the full option sets and rationales
in the authored source, negation scope, final versus superseded instructions,
roles in dialogues, and the evidence needed for each label.

Missing information is distinct from contradiction. For example, an unstated
workshop fee does not establish that it is free; unrecorded consent does not
establish refusal; “only red is available” rules out green. Moderation labels use
the supplied local rule, and distinguish the author's speech from reported or
educational quotations. Dates and amounts require selection or equality checks,
without calculation or calendar conversion.

The English counterparts were reviewed against the Persian questions before
freezing. Option IDs and ordering are identical, descriptive criteria are
translated, and proper names remain in Persian. Thirty Choice, ten Noul, and
eight Score questions cover all ten areas. The subset is selected, not random.

Repeatability uses eight complete scenarios (48 questions) from reading,
negation, idioms, pragmatics, scenario decisions, moderation, semantic matching,
and extraction. Each is requested twice more with the exact main payload.
Matched pairs use the three Choice questions in each of 16 scenario pairs in the
first four areas: 24 invariant and 24 contrast question pairs. Other questions
in those scenarios are correlated observations, but are not counted as designated
matched pairs.

The main dataset has 60 correct labels in each Choice option slot, 80 true and
80 false Noul labels, and Score level counts of 33 / 22 / 25 for levels 0 / 1 / 2.
Each of 80 states supports three Choice, two Noul, and one Score question. Cases
include explicit contextual clues to make labels reproducible; this can make
sarcasm, pragmatics, and injection cases easier than natural-world examples.
Finglish is only two main scenarios (12 questions), so it cannot support broad
claims about transliterated Persian.

`manifest.json` freezes data hashes and scoring thresholds. The authoritative
source is `scripts/author_dataset.py`; JSONL files and the manifest are generated
from it. Regenerate only when intentionally revising the dataset. Any correction
after evaluation requires a new revision, a record below, and a fresh run. Never
edit old run snapshots or silently relabel results.

## Revision history

- **1.0.0, 2026-09-22 UTC:** Initial reviewed dataset, frozen before smoke and full
  evaluation. No model results were used to set labels, rubrics, or thresholds.

## Pre-main runner verification

The first separate smoke run revealed independently rounded Score/probability
fields: score 1.99 with probabilities 0.00 / 0.00 / 1.00. Before the main run,
response validation was corrected to allow a 0.005 rounding error per displayed
probability and score component (scoring implementation 1.0.1). The full run uses
this frozen implementation. Raw returned values are retained without
renormalization. Dataset content, gold, and accuracy/confidence thresholds did
not change. The initial smoke artifacts are preserved as `results/smoke-v1`;
the verified smoke run is separate. That earlier development snapshot uses
scoring implementation 1.0.0 and is not silently rescored by version 1.0.1.
