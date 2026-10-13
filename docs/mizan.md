# Mizan on Apple Silicon

Mizan v3 3B Q8 scored **97.1% Choice accuracy, 98.8% Noul accuracy, and 100%
within Score tolerance** on the frozen general Persian benchmark. It exceeded
both Jeff models on these metrics. Compared with the historical Jev run, Mizan
had lower Choice and Noul accuracy, but lower Score MAE (0.0396 versus 0.0709
rubric levels). Literary-bank accuracy was **28.2%**, below its 31.6%
majority-label baseline. Classical meaning recognition was **87.5%** and
situation matching **75.0%**. These results apply to this checkpoint and dataset.

## Evaluated configuration

The publisher's [Mizan v3 Q8 GGUF](https://huggingface.co/Nimruz/Mizan-v3-3B-GGUF/tree/b106f7d9839fad0e212d73bb1ea9d53b29e9713d)
ran on 2026-10-13 UTC on an **Apple M4 with 16 GB unified memory**, macOS
27.0.1, using llama.cpp's Metal backend. This is the 8-bit quantized release,
not the original BF16 checkpoint or the publisher's default Q4 build.

- Model file: `mizan-v3-3b-Q8_0.gguf`, 3,093,146,176 bytes.
- Model revision: `b106f7d9839fad0e212d73bb1ea9d53b29e9713d`.
- Model SHA-256: `5972c6520ec0330daee1ecaa16642caeb1273e75302106106003c0c2373fb822`.
- Runtime: official [llama.cpp b11600](https://github.com/ggml-org/llama.cpp/releases/tag/b11600)
  macOS arm64 binary, commit `ace20f679e30a39c09a7b17bec14199855469633`.
- Client: `typesafe-sdk==0.7.1`; dataset revisions 1.0.0; scoring version 1.0.1.

The GGUF's embedded calibration temperatures were used unchanged. Context,
batch, and micro-batch sizes were 8,192 tokens, with one server slot and GPU
offloading enabled. Requests ran sequentially through `/v1/systemone`. The six
general questions in each scenario shared a request; literary and classical
questions ran individually. No translation, prompt tuning, or model judge was
introduced. Smoke evaluations are separate from full-run scores.

Use the pinned runtime above on Apple Silicon. Earlier llama.cpp builds can
produce incorrect Clef decision probabilities because of a
[Metal matrix-operation fusion bug](https://github.com/ggml-org/llama.cpp/pull/30100).
The initial b11443 runs in `*-v1/` are excluded from this comparison. Two
diagnostic requests changed from incorrect, nearly uniform probabilities on
b11443 to the correct answers above 93% probability on b11600, with the same
checkpoint and inputs. The reported results use fresh `*-v2/` runs throughout.

## General results

Jev and Jeff results below are historical runs, not fresh evaluations. All use
the same frozen questions, answer order, gold labels, and scoring.

| Metric | Mizan v3 Q8 | Jeff 2B | Jev |
|---|---:|---:|---:|
| Choice accuracy | 233/240 · 97.1% | 224/240 · 93.3% | 239/240 · 99.6% |
| Noul accuracy | 158/160 · 98.8% | 144/160 · 90.0% | 159/160 · 99.4% |
| Score within ±0.5 levels | 80/80 · 100% | 67/80 · 83.8% | 76/80 · 95.0% |
| Choice Brier ↓ | 0.0441 | 0.1069 | 0.0112 |
| Noul Brier ↓ | 0.0090 | 0.0798 | 0.0120 |
| Score MAE, rubric levels ↓ | 0.0396 | 0.2794 | 0.0709 |

All 624 general answers were valid across 106 requests, including diagnostics.
Mizan answered both questions correctly in 24/24 invariant pairs and 23/24
contrast pairs. English instructions changed 1/48 decisions. None of the 48
three-observation repeatability groups changed decisions.

Errors included identifying the traveler as their own host (`s021q3`), misreading
the idiom «آب خوردنه» (`s034q1`), and classifying a broken PDF export as cosmetic
despite the supplied CSV workaround (`s049q1`). The last scenario also produced
an incorrect high-confidence Noul answer (`s049q5`). Perfect Score tolerance
therefore does not imply consistent decisions across question types.

## Literary results and controls

| Task or condition | Mizan v3 Q8 | Jeff 2B | Jev |
|---|---:|---:|---:|
| Literary question bank | 158/560 · 28.2% | 154/560 · 27.5% | 283/557 · 50.8% |
| Classical paraphrase from verse | 21/24 · 87.5% | 20/24 · 83.3% | 24/24 · 100% |
| Classical application from verse | 18/24 · 75.0% | 20/24 · 83.3% | 24/24 · 100% |
| Both main tasks on an excerpt | 15/24 · 62.5% | 17/24 · 70.8% | 24/24 · 100% |
| Application with supplied prose meaning | 24/24 · 100% | 23/24 · 95.8% | 24/24 · 100% |
| Application without the passage | 6/24 · 25.0% | 6/24 · 25.0% | 6/24 · 25.0% |

Jev had three invalid literary responses. On the common 557 valid questions,
Mizan scored 158/557 (28.4%), Jeff 2B 154/557 (27.6%), and Jev 283/557 (50.8%).
The full bank's uniform-random baseline is 25%, and its majority-label baseline
is 31.6%. Mizan's four-answer lead over Jeff 2B does not establish a meaningful
advantage on this extracted bank, which retains
[OCR and unverified-answer-key limitations](../data/poetry/REVIEW.md).

Supplying prose meanings corrected all six classical application errors;
removing the passage reduced application accuracy by 50 percentage points.
This supports passage use on these selected examples and suggests difficulty
extracting some verse meanings. Prose also simplifies the task and can introduce
author cues. The [24-excerpt pilot](../data/classical/REVIEW.md) is assistant-authored,
has correlated controls, and does not establish representative literary ability.

## Request time and coverage

| Suite | Requests | Valid evaluations | Total request time | Median request time |
|---|---:|---:|---:|---:|
| General, including diagnostics | 106 | 624/624 | 128.25 s | 1,235 ms |
| Literary question bank | 560 | 560/560 | 300.98 s | 532 ms |
| Classical, including controls | 96 | 96/96 | 57.81 s | 617 ms |
| Total | 762 | 1,280/1,280 | 487.04 s | — |

There were no failed requests, invalid answers, model mismatches, or truncated
inputs. The 32 smoke evaluations across 22 requests and two runtime diagnostics
are excluded from these totals. Timings include local HTTP and SDK handling,
exclude download and model loading, and come from one sequential run per suite.
They are not controlled throughput or cross-hardware comparisons. Local
inference incurred no API charges; hardware and electricity costs were not measured.

## Run locally

From the repository root, download the pinned publisher checkpoint and runtime.
The weights and binaries stay in the Git-ignored `.tmp/` directory. Allow about
3.2 GB for the download and runtime, plus operating-system headroom.

```sh
mkdir -p .tmp/mizan/models
curl -fL --retry 3 \
  https://github.com/ggml-org/llama.cpp/releases/download/b11600/llama-b11600-bin-macos-arm64.tar.gz \
  -o .tmp/mizan/llama-b11600-bin-macos-arm64.tar.gz
printf '%s\n' 'a9c10e58e42603d67a3ad3cbe991d420e31d350937e11775db55011e25536668  .tmp/mizan/llama-b11600-bin-macos-arm64.tar.gz' | shasum -a 256 -c -
tar -xzf .tmp/mizan/llama-b11600-bin-macos-arm64.tar.gz -C .tmp/mizan
curl -fL --retry 3 \
  https://huggingface.co/Nimruz/Mizan-v3-3B-GGUF/resolve/b106f7d9839fad0e212d73bb1ea9d53b29e9713d/mizan-v3-3b-Q8_0.gguf \
  -o .tmp/mizan/models/mizan-v3-3b-Q8_0.gguf
printf '%s\n' '5972c6520ec0330daee1ecaa16642caeb1273e75302106106003c0c2373fb822  .tmp/mizan/models/mizan-v3-3b-Q8_0.gguf' | shasum -a 256 -c -
```

Verify both checksum commands succeed before starting the server. Reuse existing
verified downloads. In a separate terminal, leave this server running:

```sh
.tmp/mizan/llama-b11600/llama-server \
  -m .tmp/mizan/models/mizan-v3-3b-Q8_0.gguf \
  --alias mizan-v3-3b-q8_0 \
  -c 8192 -b 8192 -ub 8192 -ngl 99 --parallel 1 \
  --host 127.0.0.1 --port 8766
```

Once `/health` returns `{"status":"ok"}`, run the benchmark:

```sh
uv sync --locked
curl --noproxy '*' --fail http://127.0.0.1:8766/health
uv run jev-benchmark run --local-url http://127.0.0.1:8766 --model mizan-v3-3b-q8_0 --suite smoke --output results/mizan-q8-general-smoke
uv run jev-benchmark run --local-url http://127.0.0.1:8766 --model mizan-v3-3b-q8_0 --suite full --output results/mizan-q8-general-full
uv run jev-benchmark run --local-url http://127.0.0.1:8766 --model mizan-v3-3b-q8_0 --data data/poetry --suite smoke --output results/mizan-q8-poetry-smoke
uv run jev-benchmark run --local-url http://127.0.0.1:8766 --model mizan-v3-3b-q8_0 --data data/poetry --suite full --output results/mizan-q8-poetry-full
uv run jev-benchmark run --local-url http://127.0.0.1:8766 --model mizan-v3-3b-q8_0 --data data/classical --suite smoke --output results/mizan-q8-classical-smoke
uv run jev-benchmark run --local-url http://127.0.0.1:8766 --model mizan-v3-3b-q8_0 --data data/classical --suite full --output results/mizan-q8-classical-full
uv run jev-benchmark report results/mizan-q8-general-full
```

Use fresh output directories for later runs. Stop the server with Ctrl+C when
finished. The local runner ignores cloud credentials and proxies; no API key is
needed. The [llama.cpp endpoint documentation](https://github.com/ggml-org/llama.cpp/blob/b11600/tools/server/README.md#post-v1systemone-typesafe-compatible-system-one-api)
requires the entire Clef decision prompt to fit the micro-batch size.

## Saved artifacts

Local runs are saved in `results/mizan-q8-{general,poetry,classical}-full-v2/`,
with corresponding `smoke-v2/` runs. Each directory contains the request plan,
raw responses, scored answers, summary, and report. Runtime metadata, publisher
revisions, checksums, and server logs are in `results/mizan-evaluation-v2/`.
These directories and the weights are Git-ignored; the results in this guide
remain readable without them.

All three full reports, summaries, and scored-answer files reproduced
byte-for-byte offline. Saved wire requests match their plans; request contents,
state serialization, question and option order, and gold labels match the saved
Jeff 2B runs. The audit is recorded in
`results/mizan-evaluation-v2/verification.json`. The benchmark code and frozen
datasets were unchanged; all 125 existing tests, Ruff, and dataset preparation
checks passed.
