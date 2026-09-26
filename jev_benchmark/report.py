"""Offline, reproducible reports using only the immutable run snapshot and journal."""

import json
from collections import Counter
from pathlib import Path
from statistics import mean, median

from .data import THRESHOLDS, require
from .runner import SCORING_VERSION, write_json
from .scoring import ratio, score_answer, summarize


def read_events(path):
    """Only an unterminated final line may be discarded after a process interruption."""
    if not path.exists():
        return [], []
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    events, warnings = [], []
    for i, line in enumerate(lines):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if i == len(lines) - 1 and not line.endswith("\n"):
                warnings.append("Ignored an incomplete trailing journal record.")
            else:
                raise ValueError(f"Corrupt journal line {i + 1}: {exc.msg}") from exc
    return events, warnings


def analyze(meta, events):
    require(
        meta["schema_version"] == 1 and meta["scoring_version"] == SCORING_VERSION,
        "Unsupported run/scoring version",
    )
    require(meta["dataset_manifest"]["thresholds"] == THRESHOLDS, "Scoring thresholds changed")
    jobs = {j["id"]: j for j in meta["jobs"]}
    require(len(jobs) == len(meta["jobs"]), "Duplicate planned request")
    finished = {}
    for e in events:
        require(
            e.get("job_id") in jobs and e.get("event") in {"started", "finished"},
            "Unknown journal event or job",
        )
        if e["event"] == "finished":
            require(e["job_id"] not in finished, "Duplicate finished request")
            finished[e["job_id"]] = e
    rows, warnings = [], []
    for job_id, job in jobs.items():
        event = finished.get(job_id)
        raw = event.get("raw_response") if event else None
        answers = raw.get("answers", {}) if isinstance(raw, dict) else {}
        if not isinstance(answers, dict):
            answers = {}
        if set(answers) - set(job["request"]["questions"]):
            warnings.append(f"Unexpected answer IDs returned for {job_id}.")
        for q in job["scenario"]["questions"]:
            qid = q["id"]
            row = {
                "job_id": job_id,
                "question_id": qid,
                "phase": job["phase"],
                "observation": job["observation"],
                "primitive": q["type"],
                "category": job["scenario"]["category"],
                "tags": job["scenario"]["tags"],
                "state": job["scenario"]["state"],
                "question": job["request"]["questions"][qid],
                "gold": job["gold"][qid],
                "answer": answers.get(qid),
                "returned_model": event.get("returned_model") if event else None,
            }
            if "source" in job["scenario"]:
                row["source"] = job["scenario"]["source"]
            if event is None:
                row.update(status="not_completed", error="Request did not finish")
            elif event["status"] != "ok":
                row.update(status="error", error=event["error"])
            else:
                try:
                    row["metrics"] = score_answer(
                        row["question"], row["gold"]["expected"], row["answer"]
                    )
                    row["status"] = "ok"
                except ValueError as exc:
                    row.update(status="error", error=str(exc))
            rows.append(row)
    main = [r for r in rows if r["phase"] in {"main", "smoke"}]
    baseline = {r["question_id"]: r for r in main}
    phases = {
        p: summarize([r for r in rows if r["phase"] == p])
        for p in sorted({r["phase"] for r in rows})
    }
    pairs = {}
    for kind in ("invariant", "contrast"):
        selected = [p for p in meta["pairs"] if p["kind"] == kind]
        complete = [
            p for p in selected if all(baseline[q]["status"] == "ok" for q in p["questions"])
        ]
        both = sum(all(baseline[q]["metrics"]["correct"] for q in p["questions"]) for p in complete)
        relation = sum(
            (
                baseline[p["questions"][0]]["metrics"]["predicted"]
                == baseline[p["questions"][1]]["metrics"]["predicted"]
            )
            == (kind == "invariant")
            for p in complete
        )
        pairs[kind] = {
            "planned": len(selected),
            "complete": len(complete),
            "both_correct": both,
            "both_correct_rate": ratio(both, len(complete)),
            "expected_decision_relation": ratio(relation, len(complete)),
        }
    english = [r for r in rows if r["phase"] == "english"]
    paired_en = [
        r for r in english if r["status"] == "ok" and baseline[r["question_id"]]["status"] == "ok"
    ]
    paired_fa = [baseline[r["question_id"]] for r in paired_en]
    changed = sum(
        r["metrics"]["predicted"] != baseline[r["question_id"]]["metrics"]["predicted"]
        for r in paired_en
    )
    repeat = []
    for qid in sorted({r["question_id"] for r in rows if r["phase"] == "repeat"}):
        obs = [baseline[qid]] + [
            r for r in rows if r["phase"] == "repeat" and r["question_id"] == qid
        ]
        valid = [r for r in obs if r["status"] == "ok"]
        entry = {
            "question_id": qid,
            "primitive": baseline[qid]["primitive"],
            "valid_observations": len(valid),
        }
        if len(valid) == 3:
            entry["decision_changed"] = len({r["metrics"]["predicted"] for r in valid}) > 1
            values = [r["metrics"]["numeric"] for r in valid if "numeric" in r["metrics"]]
            entry["numeric_range"] = max(values) - min(values) if values else None
            if entry["primitive"] == "choice":
                keys = baseline[qid]["question"]["criteria"]
                entry["max_probability_range"] = max(
                    max(r["answer"]["probabilities"][k] for r in valid)
                    - min(r["answer"]["probabilities"][k] for r in valid)
                    for k in keys
                )
        repeat.append(entry)
    complete_repeat = [r for r in repeat if r["valid_observations"] == 3]
    latencies = [e["elapsed_seconds"] for e in finished.values()]
    usages = [e.get("usage", {}) for e in finished.values()]
    usage = {
        key: sum(u[key] for u in usages if isinstance(u.get(key), int))
        for key in ("input_tokens", "output_tokens")
    }
    usage["requests_with_usage"] = sum(
        all(isinstance(u.get(k), int) for k in ("input_tokens", "output_tokens")) for u in usages
    )
    status_counts = Counter(r["status"] for r in rows)
    summary = {
        "schema_version": 1,
        "suite": meta["suite"],
        "dataset_revision": meta["dataset_manifest"]["revision"],
        "requested_model": meta["requested_model"],
        "returned_models": dict(
            Counter(e["returned_model"] for e in finished.values() if e.get("returned_model"))
        ),
        "model_mismatch_requests": sum(e.get("model_mismatch", False) for e in finished.values()),
        "completion": {
            "planned_questions": len(rows),
            "valid_answers": status_counts["ok"],
            "failed_answers": status_counts["error"],
            "not_completed": status_counts["not_completed"],
            "planned_requests": len(jobs),
            "finished_requests": len(finished),
            "failed_requests": sum(e["status"] != "ok" for e in finished.values()),
            "complete": status_counts["ok"] == len(rows),
        },
        "phases": phases,
        "main": summarize(main),
        "categories": {
            c: summarize([r for r in main if r["category"] == c])
            for c in sorted({r["category"] for r in main})
        },
        "tags": {
            t: summarize([r for r in main if t in r["tags"]])
            for t in sorted({t for r in main for t in r["tags"]})
        },
        "pairs": pairs,
        "english_comparison": {
            "planned": len(english),
            "complete_pairs": len(paired_en),
            "persian": summarize(paired_fa),
            "english": summarize(paired_en),
            "decision_changes": changed,
        },
        "repeatability": {
            "planned": len(repeat),
            "complete_triples": len(complete_repeat),
            "decision_changes": sum(r["decision_changed"] for r in complete_repeat),
            "questions": repeat,
        },
        "latency_seconds": {
            "total": sum(latencies),
            "median": median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "usage": usage,
        "warnings": warnings,
    }
    if meta["dataset_manifest"].get("benchmark") == "poetry":
        counts = Counter(r["gold"]["expected"] for r in main)
        majority = max("ABCD", key=lambda label: counts[label])
        summary.update(
            benchmark="poetry",
            label_counts={label: counts[label] for label in "ABCD"},
            baselines={
                "random_accuracy": 0.25,
                "majority_label": majority,
                "majority_correct": counts[majority],
                "majority_accuracy": ratio(counts[majority], len(main)),
                "planned_questions": len(main),
            },
        )
    if meta["dataset_manifest"].get("benchmark") == "classical_transfer":
        from .classical_report import classical_metrics

        summary.update(benchmark="classical_transfer", classical=classical_metrics(rows))
    return summary, rows


def pct(value):
    return "—" if value is None else f"{value:.1%}"


def decimal(value):
    return "—" if value is None else f"{value:.4f}"


def clean(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def metric_table(metrics):
    lines = [
        "| Primitive | Valid / planned | Failures / unfinished | Accuracy / within ±0.5 | Brier "
        "| MAE (levels) | Normalized MAE |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for kind, m in metrics.items():
        lines.append(
            f"| {kind} | {m['valid']} / {m['planned']} | {m['failures']} / {m['not_completed']} | "
            f"{pct(m.get('accuracy', m.get('within_half')))} | {decimal(m.get('brier'))} | "
            f"{decimal(m.get('mae'))} | {decimal(m.get('normalized_mae'))} |"
        )
    return lines


def render_markdown(meta, summary, rows):
    if meta["dataset_manifest"].get("benchmark") == "classical_transfer":
        from .classical_report import render_classical_markdown

        return render_classical_markdown(meta, summary, rows)
    if meta["dataset_manifest"].get("benchmark") == "poetry":
        return render_poetry_markdown(meta, summary, rows)
    c = summary["completion"]
    lines = [
        "# Jev Persian benchmark",
        "",
        f"Run started: {meta['created_at']}. Dataset revision: {summary['dataset_revision']}.",
        "",
        f"**{'COMPLETE' if c['complete'] else 'INCOMPLETE'}: {c['valid_answers']} / "
        f"{c['planned_questions']} valid answers; "
        f"{c['failed_answers']} failed; {c['not_completed']} unfinished.** "
        f"Requests finished: {c['finished_requests']} / {c['planned_requests']} "
        f"({c['failed_requests']} failed).",
        "",
        f"Requested model: `{summary['requested_model']}`. Returned models: "
        f"`{summary['returned_models']}`. "
        f"Model mismatches: **{summary['model_mismatch_requests']}** requests.",
        "",
        "## Main Persian evaluation" if meta["suite"] == "full" else "## Smoke suite",
        "",
    ]
    lines += metric_table(summary["main"])
    n = summary["main"]["noul"]
    lines += [
        "",
        f"Noul precision: {pct(n['precision'])}; recall: {pct(n['recall'])} (n={n['valid']}).",
        "",
        "Choice Brier is the sum across classes (range 0–2); Noul Brier is binary (0–1). "
        "Score success means within ±0.5 levels, inclusive. Missing and invalid answers are "
        "excluded from accuracy, "
        "and counted as failures. No combined accuracy across different primitives is reported.",
        "",
        "## High-confidence diagnostics",
        "",
        "Choice/Score use returned confidence ≥0.8; Noul uses p≤0.2 or p≥0.8. "
        "Coverage uses valid answers as its denominator. These thresholds are diagnostic, not "
        "production guarantees.",
        "",
        "| Primitive | High-confidence n / valid n | Coverage | Accuracy / within ±0.5 |",
        "|---|---:|---:|---:|",
    ]
    for kind, m in summary["main"].items():
        lines.append(
            f"| {kind} | {m['high_confidence_n']} / {m['valid']} | "
            f"{pct(m['high_confidence_coverage'])} | {pct(m['high_confidence_accuracy'])} |"
        )
    for section, groups in [
        ("Task areas", summary["categories"]),
        ("Language and content tags", summary["tags"]),
    ]:
        lines += [
            "",
            f"## {section}",
            "",
            "Counts are valid / planned. Tags overlap; they are not independent samples.",
            "",
            "| Group | Choice n; accuracy | Noul n; accuracy | Score n; MAE; within ±0.5 |",
            "|---|---:|---:|---:|",
        ]
        for name, ms in groups.items():
            a, b, d = ms["choice"], ms["noul"], ms["score"]
            lines.append(
                f"| {name} | {a['valid']}/{a['planned']}; {pct(a['accuracy'])} | "
                f"{b['valid']}/{b['planned']}; {pct(b['accuracy'])} | "
                f"{d['valid']}/{d['planned']}; {decimal(d['mae'])}; {pct(d['within_half'])} |"
            )
    if meta["suite"] == "full":
        lines += [
            "",
            "## Matched pairs",
            "",
            "| Pair type | Complete / planned | Both correct | Expected decision relation |",
            "|---|---:|---:|---:|",
        ]
        for kind, m in summary["pairs"].items():
            lines.append(
                f"| {kind} | {m['complete']} / {m['planned']} | {m['both_correct']} "
                f"({pct(m['both_correct_rate'])}) | {pct(m['expected_decision_relation'])} |"
            )
        en = summary["english_comparison"]
        lines += [
            "",
            "## English-instruction diagnostic",
            "",
            f"Matched complete pairs: {en['complete_pairs']} / {en['planned']}. Decision "
            f"changes: {en['decision_changes']}. "
            "Both tables use only the same complete pairs. States stay Persian; only "
            "instructions and descriptive criteria change. "
            "Names remain Persian and option IDs/order stay fixed. This small subset is not a "
            "full English benchmark.",
            "",
            "### Matched Persian subset",
            "",
        ]
        lines += metric_table(en["persian"])
        lines += ["", "### English counterparts", ""] + metric_table(en["english"])
        rep = summary["repeatability"]
        lines += [
            "",
            "## Repeatability",
            "",
            f"Complete triples: {rep['complete_triples']} / {rep['planned']}; questions whose "
            f"decisions changed: {rep['decision_changes']}. "
            "Each triple contains the main answer and two identical-payload reruns. Score "
            "decisions round to the nearest level, "
            "with half levels rounding upward. Numeric variation is max minus min across three "
            "observations.",
            "",
            "| Primitive | Complete triples | Decisions changed | Mean numeric range | Max "
            "numeric range |",
            "|---|---:|---:|---:|---:|",
        ]
        for kind in ("choice", "noul", "score"):
            selected = [
                r
                for r in rep["questions"]
                if r["primitive"] == kind and r["valid_observations"] == 3
            ]
            values = [
                r["numeric_range"] if kind != "choice" else r["max_probability_range"]
                for r in selected
            ]
            lines.append(
                f"| {kind} | {len(selected)} | {sum(r['decision_changed'] for r in selected)} | "
                f"{decimal(mean(values) if values else None)} | "
                f"{decimal(max(values) if values else None)} |"
            )
        lines += [
            "",
            "Choice variation is the largest per-option probability range. Noul variation uses "
            "p(yes); Score uses rubric levels.",
        ]
    usage, latency = summary["usage"], summary["latency_seconds"]
    lines += [
        "",
        "## Resources",
        "",
        f"Request time total: {latency['total']:.3f}s; median: {decimal(latency['median'])}s; "
        f"max: {decimal(latency['max'])}s. "
        "Times include SDK retries and local transport handling. "
        f"Reported tokens: {usage['input_tokens']} input, {usage['output_tokens']} output. "
        f"Usage available for {usage['requests_with_usage']} / {c['finished_requests']} "
        f"finished requests; unreported usage is unknown, not zero.",
        "",
        "## Failed main examples",
        "",
        "All incorrect main answers and main API/validation failures are listed below. Full "
        "diagnostic answers are in `answers.jsonl`.",
    ]
    failed = [
        r
        for r in rows
        if r["phase"] in {"main", "smoke"} and (r["status"] != "ok" or not r["metrics"]["correct"])
    ]
    if not failed:
        lines += ["", "None."]
    for r in failed:
        q, g = r["question"], r["gold"]
        expected = g["expected"]
        if r["primitive"] == "choice":
            expected = f"{expected}: {q['criteria'][expected]}"
        elif r["primitive"] == "score":
            expected = f"{expected}: {q['criteria'][expected]}"
        lines += [
            "",
            f"### {r['question_id']} — {r['category']} / {r['primitive']}",
            "",
            f"State: {clean(r['state']['text'])}",
            "",
            f"Question: {clean(q['instructions'])}",
            "",
            f"Expected: {clean(expected)}. Rationale: {clean(g['rationale'])}",
            "",
            f"Observed: `{clean(json.dumps(r['answer'], ensure_ascii=False))}`"
            if r["status"] == "ok"
            else f"Failure: {clean(r['error'])}",
        ]
    lines += [
        "",
        "## Interpretation limits",
        "",
        "This is a small synthetic benchmark authored and reviewed by one model, without "
        "independent human annotation. "
        "Questions within a scenario and matched pairs are correlated. Option labels are "
        "balanced, but scenarios and diagnostic "
        "subsets are deliberately selected, not representative samples of Persian use. Score "
        "gold levels reflect authored rubrics. "
        "Some rubric tasks are simple evidence/completeness judgments. High scores here do not "
        "establish general Persian fluency "
        "or production safety. English and repeatability diagnostics are excluded from main "
        "metrics. "
        "Arithmetic and calendar conversion are outside scope.",
        "",
    ]
    for warning in summary["warnings"]:
        lines += [f"Warning: {warning}", ""]
    return "\n".join(lines)


def render_poetry_markdown(meta, summary, rows):
    c, m = summary["completion"], summary["main"]["choice"]
    baseline, manifest = summary["baselines"], meta["dataset_manifest"]
    stats = manifest["preparation"]
    lines = [
        "# Jev Persian poetry and literary semantics",
        "",
        f"Run started: {meta['created_at']}. Dataset revision: {summary['dataset_revision']}. "
        f"Suite: {summary['suite']}.",
        "",
        f"**{'COMPLETE' if c['complete'] else 'INCOMPLETE'}: {m['correct']} correct / "
        f"{m['valid']} valid / {m['planned']} planned; {c['failed_answers']} failed; "
        f"{c['not_completed']} unfinished.** Requests: {c['finished_requests']} / "
        f"{c['planned_requests']} finished ({c['failed_requests']} failed).",
        "",
        f"Requested model: `{summary['requested_model']}`. Returned models: "
        f"`{summary['returned_models']}`. Model mismatches: "
        f"**{summary['model_mismatch_requests']}** requests.",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Exact Choice accuracy | {pct(m['accuracy'])} |",
        f"| Choice Brier (lower is better; range 0–2) | {decimal(m['brier'])} |",
        f"| High-confidence answers (confidence ≥0.8) | {m['high_confidence_n']} / {m['valid']} |",
        f"| High-confidence coverage | {pct(m['high_confidence_coverage'])} |",
        f"| High-confidence accuracy | {pct(m['high_confidence_accuracy'])} |",
        f"| Uniform random baseline | {pct(baseline['random_accuracy'])} |",
        f"| Majority-label baseline ({baseline['majority_label']}) | "
        f"{baseline['majority_correct']} / {baseline['planned_questions']} · "
        f"{pct(baseline['majority_accuracy'])} |",
        "",
        "Accuracy and Brier use valid answers only. API and response-validation failures are "
        "reported separately. Baselines use all planned questions in this suite; compare "
        "accuracy with them only once coverage is complete. Confidence is diagnostic, not a "
        "guarantee of correctness.",
        "",
        "Gold labels: " + "; ".join(f"{k}={v}" for k, v in summary["label_counts"].items()) + ". "
        "Source labels 1–4 map to A–D without shuffling.",
        "",
        "## Data and interpretation",
        "",
        f"{stats['source_questions']} source questions; {stats['excluded_questions']} documented "
        f"exclusions; {stats['retained_questions']} retained. "
        f"{stats['repaired_questions']} questions have recorded extraction repairs. "
        "Each request includes the complete reviewed question stem and its four options. "
        "Only the model's selected option is scored against the supplied key; no model judge "
        "or generated explanation is used.",
        "",
        "The bank includes classical and modern poetry, prose, and religious passages. "
        "It tests literary interpretation/comparison, not exclusively classical poetry. "
        "Source answer keys were retained without independent reannotation. Residual OCR "
        "errors and unverified half-verse order remain; this is an exploratory extracted "
        "question bank, not a critical edition. Repeated verses and related questions are "
        "correlated. Poet attribution is unavailable, so no per-poet claims are supported. "
        "High scores do not establish comprehensive poetry understanding. Historical LLM "
        "results used different prompts/subsets and are not directly comparable.",
        "",
        "The 12-question smoke suite is a fixed, label-balanced subset of the full set. "
        "Its results are separate and are never added to the full-run denominator.",
        "",
        "## Resources",
        "",
    ]
    usage, latency = summary["usage"], summary["latency_seconds"]
    lines += [
        f"Request time: {latency['total']:.3f}s total; {decimal(latency['median'])}s median; "
        f"{decimal(latency['max'])}s maximum, including retries. Reported tokens: "
        f"{usage['input_tokens']} input, {usage['output_tokens']} output. Usage is available "
        f"for {usage['requests_with_usage']} / {c['finished_requests']} finished requests; "
        "unreported usage is unknown, not zero.",
        "",
        "## Incorrect or incomplete examples",
        "",
        "All unsuccessful questions are included below. Full responses and probabilities "
        "are preserved in `answers.jsonl` and `requests.jsonl`.",
    ]
    failed = [r for r in rows if r["status"] != "ok" or not r["metrics"]["correct"]]
    if not failed:
        lines += ["", "None."]
    for row in failed:
        source = row["source"]
        lines += [
            "",
            f"### {row['question_id']} — source question {source['question_id']}, "
            f"page {source['page']}",
            "",
            clean(row["state"]["text"]),
            "",
        ]
        for index, (label, text) in enumerate(row["question"]["criteria"].items(), 1):
            lines.append(f"- {label} (source {index}): {clean(text.replace(chr(10), ' / '))}")
        observed = (
            json.dumps(row["answer"], ensure_ascii=False) if row["status"] == "ok" else row["error"]
        )
        lines += [
            "",
            f"Expected: **{row['gold']['expected']}**. "
            f"{'Observed' if row['status'] == 'ok' else 'Failure'}: {clean(observed)}.",
        ]
    for warning in summary["warnings"]:
        lines += ["", f"Warning: {warning}"]
    return "\n".join(lines) + "\n"


def build_report(directory):
    directory = Path(directory)
    meta = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    events, warnings = read_events(directory / "requests.jsonl")
    summary, rows = analyze(meta, events)
    summary["warnings"].extend(warnings)
    write_json(directory / "summary.json", summary)
    (directory / "answers.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    (directory / "report.md").write_text(render_markdown(meta, summary, rows), encoding="utf-8")
    return summary
