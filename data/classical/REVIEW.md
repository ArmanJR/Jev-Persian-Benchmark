# Classical meaning and application — pilot 1.0.0

This is a **24-excerpt pilot**, with six excerpts each from Sa’adi, Hafez, Rumi,
and Ferdowsi. It asks whether Jev can identify a local poetic meaning and transfer
it to a newly written situation. See the [latest run and worked examples](../../docs/classical-poetry.md)
for the recorded results, exact question wording, and Jev's selected answers.

## What is tested

Each excerpt produces four **independent one-question Choice requests**:

| Condition | Input | Decision | Included in main results? |
|---|---|---|---|
| Paraphrase | Original verse | Best of four contemporary-Persian interpretations | Yes |
| Application | Original verse | Best of four newly authored situations | Yes |
| Prose control | Authored contemporary-Persian meaning | Same application choices | No |
| No-poem control | Fixed notice that no passage is provided | Same application choices | No |

There are **48 main questions and 48 controls**. The application request never
includes the paraphrase question, candidate explanations, rationale, poet name,
source title, or answer key. Each request is stateless; prior answers are not fed
into later questions. Controls retain the exact application instruction, option
texts, option order, and key; only the passage and question ID change.

Six banks contain four situations each. Every bank is reused for four excerpts,
with a different correct situation for each. Thus simply preferring one admirable
or plausible situation cannot solve the whole bank. Situations express different
relations, not just positive versus negative conduct. Each main task has six gold
answers per label A–D. Correct paraphrase positions and situation-bank ordering
are deterministically shuffled, independently of Jev outputs.

The eight-question smoke set contains both main tasks for the first excerpt of
each poet. It is a subset, not a holdout, and is not necessarily label-balanced.
Smoke does not run controls or contribute additional observations to full scores.

## Source and annotation quality

[authored.json](authored.json) is the authoritative annotation file. It records
source URLs, zero-based hemistich ranges, checked quotations, prose controls,
interpretation choices, situation-bank membership, rationales, and review notes.
The **first authored paraphrase option is the key**, before deterministic
shuffling. Each situation's `excerpt_id` names the excerpt it best illustrates.

[sources.json](sources.json) contains the original verse columns retrieved from
15 Ganjoor pages, along with page titles, retrieval timestamps, and hashes of the
retrieved HTML. No AI-generated glosses or reader comments are imported. These
are public-domain historical poems; new candidate interpretations and situations
were authored for this pilot. The full HTML is not retained. Preparation verifies
every selected quotation against the stored verse columns without normalizing
away punctuation, diacritics, or half-verse ordering.

**The implementing assistant authored and reviewed the questions. There has been
no independent human or scholarly annotation.** Source verification checks wording
and attribution to the source page, not the validity of our interpretation.
Review checked the expected meaning, competing choices, source range, and the
correspondence between original verse and application. Explicit review notes
avoid claiming one exhaustive interpretation of mystical imagery, confusing
metaphor with literal scientific fact, or treating historical advice as modern law.

This deliberately small set favors interpretable, often familiar or didactic
passages. Most excerpts are short; the elephant passage is longer. Some excerpts
share a source section or closely related themes. It is not a representative
sample of the four poets, a test of whole-poem interpretation, or a substitute for
independent Persian-literature review. The Persian poems retain their occasional
Arabic phrases. Neither memorization nor authorship/style cues are ruled out.

## Reading the report

Read **paraphrase accuracy, application accuracy, and both-correct excerpt rate**
separately. Invalid/missing responses are excluded from valid-answer accuracy and
reported explicitly. Both-correct rates include both complete-pair and planned-pair
denominators. The 25% random/fixed-label baseline applies to each full main task,
not to a combined pair event or an unbalanced smoke subset.

Control comparisons use only the **same complete pairs** and report improvements
and regressions. Prose controls are deliberately supplied interpretations, not
independent answer-free transcriptions: an improvement suggests a barrier in
extracting the intended meaning, but can also reflect simplification or shared
author wording. No-poem accuracy probes choices-only shortcuts; high performance
there is not poetry understanding. Shared option banks make controls correlated,
so their 48 questions must not be counted as 48 additional independent excerpts.

All raw responses are retained, including consistency failures. Do not change
keys, prompts, thresholds, or exclusions in response to Jev's results. Freeze a new
documented revision before evaluating an amended dataset in a fresh directory.

## Reproduce or revise

```sh
uv run scripts/prepare_classical.py --check
uv run jev-benchmark validate --data data/classical
uv run --env-file .env jev-benchmark run --data data/classical --suite smoke --output results/classical-smoke-v1
uv run --env-file .env jev-benchmark run --data data/classical --suite full --output results/classical-full-v1
uv run jev-benchmark report results/classical-full-v1
```

Normal preparation and report generation work offline. Edit `authored.json`, bump
its revision, document the change here, then run `uv run scripts/prepare_classical.py`.
Never edit generated `scenarios.jsonl`, `gold.jsonl`, or `manifest.json` directly.
The generator refuses changed content under an existing frozen revision.

`--fetch-sources` is an initial-import operation: it refuses to overwrite an
existing source snapshot. A new source collection belongs in a separate revision
directory, with quotation selections reviewed before evaluation.

- **1.0.0:** Initial 24-excerpt pilot, frozen before any live Jev request.
