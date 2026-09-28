# Jeff on Apple Silicon

Jeff-Qwen3.5-2B scored **93.3% Choice accuracy, 90.0% Noul accuracy, and 83.8%
within Score tolerance** on the general Persian benchmark. Its literary-bank
accuracy was **27.5%**, below the 31.6% majority-label baseline. See the
[main comparison](../README.md#general-persian-performance) for Jev and Laya results.

## Evaluated configuration

Both checkpoints ran on 2026-09-28 UTC using the official Jeff MLX server on an
**Apple M4 with 16 GB unified memory, macOS 27.0**. Backbone weights were BF16,
without quantization. The checkpoint's prompt layout and fitted temperature were
used unchanged. No translation, prompt tuning, or model judge was introduced.

- [Jeff source](https://github.com/firelex/jeff/tree/985797fa2040d1c7a14822a96123c055800d5d09):
  `985797fa2040d1c7a14822a96123c055800d5d09` (Jeff 0.2.0).
- [0.8B checkpoint](https://huggingface.co/mstrasser/Jeff-Qwen3.5-0.8B/tree/987825634b36300f6eb2131e49b6d8a1b1205228):
  `987825634b36300f6eb2131e49b6d8a1b1205228`.
- [2B checkpoint](https://huggingface.co/mstrasser/Jeff-Qwen3.5-2B/tree/f2d993c311959e542494d02d72b42a8f5c166ddb):
  `f2d993c311959e542494d02d72b42a8f5c166ddb`.
- Runtime: Python 3.14.7, MLX/MLX Metal 0.32.2, MLX-LM 0.31.3,
  Transformers 5.17.0, PyTorch 2.14.0, and TypeSafe SDK 0.7.1.

The benchmark used dataset revisions 1.0.0 and scoring version 1.0.1. Six general
questions share a request; literary and classical questions run individually.
Jeff's MLX backend evaluates the questions in a request one at a time. Each model
completed 1,280 valid evaluations over 762 requests, with no full-run failures or
model mismatches. Separate smoke checks contributed 32 evaluations per model.

Jev and Laya results are historical runs, not fresh evaluations. Requests, option
order, and gold labels were checked against those saved inputs. All six Jeff
full reports, answer files, and summaries reproduced offline from raw journals.

## Literary results and controls

| Task or condition | Jeff 0.8B | Jeff 2B | Jev |
|---|---:|---:|---:|
| Literary question bank | 120/560 · 21.4% | 154/560 · 27.5% | 283/557 · 50.8% |
| Classical paraphrase from verse | 21/24 · 87.5% | 20/24 · 83.3% | 24/24 · 100% |
| Classical application from verse | 18/24 · 75.0% | 20/24 · 83.3% | 24/24 · 100% |
| Both main tasks correct on an excerpt | 17/24 · 70.8% | 17/24 · 70.8% | 24/24 · 100% |
| Application with supplied prose meaning | 22/24 · 91.7% | 23/24 · 95.8% | 24/24 · 100% |
| Application without the passage | 6/24 · 25.0% | 6/24 · 25.0% | 6/24 · 25.0% |

Jev's literary run had three invalid responses; Jeff answered all 560 validly.
On the common 557 valid questions, the Jeff scores are 120/557 (21.5%) and
154/557 (27.6%). Neither exceeds the full bank's 31.6% majority-label baseline;
uniform random accuracy is 25%. The [literary review](../data/poetry/REVIEW.md)
documents residual OCR errors and answer keys that have not been independently
reannotated.

The classical controls are excluded from main accuracy. Supplying a prose meaning
helped both Jeff models; removing the passage reduced both to chance. This
supports passage use on these 24 selected excerpts, not representative literary
understanding. The [classical pilot review](../data/classical/REVIEW.md) describes
its authorship, passage selection, and control limitations.

## General diagnostics

Jeff 0.8B answered both questions correctly in 20/24 invariant pairs and 22/24
contrast pairs; 2B achieved 24/24 of each. Neither changed any decision across
the 48 three-observation repeat groups.

English instructions changed 4/48 decisions for 0.8B and 7/48 for 2B. On the
matched subset, 0.8B's Choice/Noul/Score successes changed from 28/30, 8/10, 3/8
to 27/30, 9/10, 4/8. For 2B they changed from 29/30, 8/10, 6/8 to 26/30, 8/10,
6/8. The states remained Persian; this is not a full English-language benchmark.

The 2B model was still weakest on scenario decisions and semantic Choice
questions (19/24 and 18/24). For example, it classified a broken PDF export as
a blocking problem despite the stated CSV workaround (`s049`), and treated
unrecorded consent as an explicit refusal on the Score rubric (`s055q6`).

## Request time

| Suite | Requests per model | 0.8B total / median | 2B total / median |
|---|---:|---:|---:|
| General, including diagnostics | 106 | 40.87 s / 386 ms | 99.84 s / 942 ms |
| Literary question bank | 560 | 77.39 s / 103 ms | 184.26 s / 239 ms |
| Classical, including controls | 96 | 108.93 s / 385 ms | 55.28 s / 299 ms |

Times include local HTTP and SDK handling, exclude model loading, and come from
one sequential run per suite. Some requests had substantial latency variation;
the 2B checkpoint download overlapped part of the 0.8B literary/classical run.
The classical timings therefore do not establish a speed advantage for 2B.
These are not controlled throughput or cross-hardware comparisons. Inference
incurred no API charges; hardware and electricity costs were not measured.

## Run locally

Use Apple Silicon with Metal available, Python 3.12+, and uv 0.12.19 or newer
for Jeff. Jeff's dependencies live in a separate environment; the benchmark
project does not need MLX or PyTorch. Allow roughly 6.2 GB for both checkpoints,
plus dependency, cache, and operating-system headroom.

From the benchmark repository root, install the pinned server and 2B model:

```sh
git clone https://github.com/firelex/jeff.git .tmp/jeff
git -C .tmp/jeff checkout --detach 985797fa2040d1c7a14822a96123c055800d5d09
(
  cd .tmp/jeff &&
  uv sync --locked --extra mac --no-dev &&
  uv run --no-sync hf download mstrasser/Jeff-Qwen3.5-2B \
    --revision f2d993c311959e542494d02d72b42a8f5c166ddb \
    --local-dir checkpoints/jeff-2b
)
```

If the checkout already exists, reuse it after verifying its revision rather
than cloning over it. Start the server in a separate terminal and leave it running:

```sh
(
  cd .tmp/jeff &&
  JEFF_BACKEND=mlx JEFF_CHECKPOINT=checkpoints/jeff-2b \
    PORT=8765 HF_HUB_OFFLINE=1 uv run --no-sync jeff-serve
)
```

Once startup completes, run the benchmark from its repository root:

```sh
uv sync --locked
curl --fail http://127.0.0.1:8765/health
uv run jev-benchmark run --local-url http://127.0.0.1:8765 --model jeff-qwen3.5-2b --suite smoke --output results/jeff-2b-general-smoke
uv run jev-benchmark run --local-url http://127.0.0.1:8765 --model jeff-qwen3.5-2b --suite full --output results/jeff-2b-general-full
uv run jev-benchmark run --local-url http://127.0.0.1:8765 --model jeff-qwen3.5-2b --data data/poetry --suite smoke --output results/jeff-2b-poetry-smoke
uv run jev-benchmark run --local-url http://127.0.0.1:8765 --model jeff-qwen3.5-2b --data data/poetry --suite full --output results/jeff-2b-poetry-full
uv run jev-benchmark run --local-url http://127.0.0.1:8765 --model jeff-qwen3.5-2b --data data/classical --suite smoke --output results/jeff-2b-classical-smoke
uv run jev-benchmark run --local-url http://127.0.0.1:8765 --model jeff-qwen3.5-2b --data data/classical --suite full --output results/jeff-2b-classical-full
uv run jev-benchmark report results/jeff-2b-general-full
```

Use fresh output directories for each run. `--local-url` accepts an HTTP(S) root
on `localhost`, `127.0.0.1`, or `[::1]`, without a path, credentials, query, or
fragment. It requires an explicit model ID; use the name returned by `/health`,
not an alias such as `jeff-latest`, to avoid model-mismatch diagnostics. It ignores
cloud credentials and proxies, sends an inert key required by the SDK, and is
intended for unauthenticated local servers.

For 0.8B, download its pinned revision and use `checkpoints/jeff-0.8b` and model
ID `jeff-qwen3.5-0.8b`. Explicit filenames avoid downloading the repository's
unrelated demonstration videos:

```sh
(
  cd .tmp/jeff &&
  uv run --no-sync hf download mstrasser/Jeff-Qwen3.5-0.8B \
    config.json decision_config.json model.safetensors readout.safetensors \
    tokenizer.json tokenizer_config.json chat_template.jinja processor_config.json \
    LICENSE NOTICE README.md \
    --revision 987825634b36300f6eb2131e49b6d8a1b1205228 \
    --local-dir checkpoints/jeff-0.8b
)
```

Stop the previous server with Ctrl+C before switching models. If MLX reports
`No Metal device available` inside a restricted agent session, run the server
from a normal Terminal with GPU access. The benchmark client also needs access
to the local port. An initial 0.8B smoke attempt failed at this connection step;
it was excluded and rerun successfully before any full evaluation.

## Saved evaluation artifacts

The measured runs are in the Git-ignored directories
`results/jeff-{0.8b,2b}-{general,poetry,classical}-full-v1/`. Each contains the
frozen request plan, raw journal, scored answers, summary, and report. The local
`results/jeff-evaluation-v1/` directory additionally records checkpoint hashes,
runtime versions, hardware, methodology, and verification results. The scores
above remain readable without those local files; model weights, environments,
and raw journals are not included in Git.
