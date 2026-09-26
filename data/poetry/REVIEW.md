# Poetry and literary semantics — revision 1.0.0

This suite evaluates four-option Persian literary questions with Jev's Choice
primitive. It includes classical and modern poetry, prose, and religious texts.
It measures interpretation and comparison in this question bank, not exclusively
classical poetry, comprehensive literary understanding, or performance by poet.

## Source and preparation

The source is the local **Persian-Poetry-Semantic-Similarity-Benchmark** project,
specifically its `data/gherabat-book/questions-outliers.json` and `answer_keys.json`.
Byte-preserved copies are in [source/](source/). The current files contain **586
questions and 1,500 answer keys**, despite an older README claiming 591 questions.
The 914 keys without corresponding questions are unused. The source identifies
`Gherabat-main.pdf`, but that PDF was not available for this review.

The smaller `preprocess-data/benchmark_dataset.json` contains **41**, not 42,
questions. Its copy, `source/legacy-41.json`, is evidence for explicitly reviewed
half-verse ordering only. Its labels, generated explanations, and historical model
responses are not imported into the evaluation.

The two main source files were untracked in the source working tree. The source
commit alone therefore does not identify them; the SHA-256 hashes in
[review.json](review.json) identify the exact bytes used.

All 586 candidates were checked for structure, IDs, answer-key coverage, options,
and extraction defects before any Jev evaluation. The extraction review also read
the stems and options; it was performed by the implementing assistant, not an
independent human annotator. It is not a fresh annotation or scholarly verification
of every answer or quotation.

**560 questions are retained and 26 excluded.** The per-question reasons in
`review.json` cover placeholders, crossed or truncated verses, missing verse pairs,
duplicated options, and a misnumbered question on page 268. No answer keys were
changed, and no questions were selected using Jev's performance.

Repairs are limited to explicit half-verse swaps supported by the legacy file,
removing duplicated option markers and a leaked question number, and correcting
`نی` to `می` in the second half of the quotation in questions 1321 and 1323.
The latter is checked against [the opening of Rumi's Masnavi on Ganjoor](https://ganjoor.net/moulavi/masnavi/daftar1/sh1).
Comparison-only Unicode folding checks the legacy ordering evidence; it does not
normalize the emitted Persian text. Apart from these recorded edits and trimming
outer whitespace from option halves, source text is preserved. A blank second
half is allowed for complete short answers and prose options.

Residual OCR errors and unverified half-verse order remain outside the documented
repairs. The older extraction is itself imperfect. Supplied answer keys have not
been independently reannotated. Treat results as an exploratory baseline on an
extracted question bank, with these limitations visible in every report.

## Evaluation protocol

Each question is one scenario and one request. Its full reviewed stem is the
state; a fixed Persian instruction asks for the appropriate semantic answer, and
the four option texts are the Choice criteria. This preserves reference passages
that the old LLM notebook's generic outlier prompt omitted.

Source option labels 1–4 map directly to A–D without reordering. Gold labels and
source metadata are stored separately from the request. No explanations, few-shot
answers, translated prompts, model judges, or derived labels are introduced.

The smoke suite selects the first, middle (`len // 2`), and last question of each
gold-label group sorted by numeric source ID: 12 questions, three per label. It
is a subset of the full set, not a holdout. Smoke results are reported separately
and never added to the full-run denominator. Prompts and labels are frozen before
smoke and are not tuned against its answers.

Accuracy and Brier use valid responses; invalid responses and API failures remain
separate. Reports show coverage, the 25% uniform-random baseline, the majority-label
baseline, confidence diagnostics, and unsuccessful examples. The full set is not
label-balanced. Related questions and repeated verses are correlated. No poet
metadata is supplied, and no poet attributions are inferred. Historical LLM
results used different prompts and subsets, so they are not direct comparisons.

## Reproduction and revisions

From the repository root:

```sh
uv run scripts/prepare_poetry.py --check
uv run jev-benchmark validate --data data/poetry
```

The preparation script reads the local source snapshots and `review.json`.
It generates `scenarios.jsonl`, `gold.jsonl`, and `manifest.json`; do not edit those
outputs directly. Normal evaluation does not depend on the original repository,
network access for data preparation, or the original PDF.

To create a new revision, document the evidence and changes in `review.json`, bump
its revision, update this review, and run `uv run scripts/prepare_poetry.py`.
Regenerating changed content under an existing frozen revision is rejected.
Never silently relabel old results or edit saved run snapshots; evaluate a new
revision in a new output directory.

- **1.0.0, 2026-09-25:** Initial reviewed import, frozen before Jev evaluation.
