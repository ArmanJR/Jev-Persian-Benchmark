"""Paired-task and matched-control diagnostics, kept separate from main accuracy."""

import json
from collections import Counter, defaultdict

from .scoring import ratio, summarize


def classical_metrics(rows):
    groups = defaultdict(dict)
    for row in rows:
        condition = row["category"] if row["phase"] in {"main", "smoke"} else row["phase"]
        groups[row["source"]["excerpt_id"]][condition] = row
    main_pairs = [g for g in groups.values() if "paraphrase" in g and "application" in g]
    complete = [
        g for g in main_pairs if all(g[t]["status"] == "ok" for t in ("paraphrase", "application"))
    ]
    outcomes = Counter(
        (g["paraphrase"]["metrics"]["correct"], g["application"]["metrics"]["correct"])
        for g in complete
    )
    paired = {
        "planned": len(main_pairs),
        "complete": len(complete),
        "both_correct": outcomes[True, True],
        "paraphrase_only": outcomes[True, False],
        "application_only": outcomes[False, True],
        "neither_correct": outcomes[False, False],
        "both_correct_rate": ratio(outcomes[True, True], len(complete)),
        "both_correct_planned_rate": ratio(outcomes[True, True], len(main_pairs)),
    }
    controls = {}
    for condition in ("prose_control", "no_poem_control"):
        selected = [g for g in groups.values() if condition in g]
        matched = [
            g
            for g in selected
            if g[condition]["status"] == "ok" and g["application"]["status"] == "ok"
        ]
        original = [g["application"] for g in matched]
        control = [g[condition] for g in matched]
        before, after = summarize(original)["choice"], summarize(control)["choice"]
        controls[condition] = {
            "planned": len(selected),
            "complete_pairs": len(matched),
            "poem": before,
            "control": after,
            "accuracy_difference": (after["accuracy"] - before["accuracy"]) if matched else None,
            "corrected": sum(
                not g["application"]["metrics"]["correct"] and g[condition]["metrics"]["correct"]
                for g in matched
            ),
            "regressed": sum(
                g["application"]["metrics"]["correct"] and not g[condition]["metrics"]["correct"]
                for g in matched
            ),
            "decision_changes": sum(
                g["application"]["metrics"]["predicted"] != g[condition]["metrics"]["predicted"]
                for g in matched
            ),
        }
    return {"paired_tasks": paired, "controls": controls, "random_accuracy": 0.25}


def render_classical_markdown(meta, summary, rows):
    from .report import clean, decimal, pct

    c = summary["completion"]
    metrics = summary["classical"]
    p = metrics["paired_tasks"]
    lines = [
        "# Jev classical Persian: meaning and application",
        "",
        f"Run started: {meta['created_at']}. Revision: {summary['dataset_revision']}. "
        f"Suite: {summary['suite']}.",
        "",
        f"**{'COMPLETE' if c['complete'] else 'INCOMPLETE'}: "
        f"{c['valid_answers']}/{c['planned_questions']} valid answers across main and controls; "
        f"{c['failed_answers']} failed; {c['not_completed']} unfinished.** "
        f"Requests finished: {c['finished_requests']}/{c['planned_requests']} "
        f"({c['failed_requests']} failed).",
        "",
        f"Requested model: `{summary['requested_model']}`. Returned models: "
        f"`{summary['returned_models']}`. Mismatches: {summary['model_mismatch_requests']}.",
        "",
        "## Main tasks — original verse only",
        "",
        "Each question is a separate request. The application request never receives the "
        "paraphrase choices or answer. Controls are excluded from main metrics.",
        "",
        "| Task | Correct / valid / planned | Accuracy | Brier | High-confidence correct rate; n |",
        "|---|---:|---:|---:|---:|",
    ]
    for task, values in summary["categories"].items():
        m = values["choice"]
        lines.append(
            f"| {task} | {m['correct']} / {m['valid']} / {m['planned']} | "
            f"{pct(m['accuracy'])} | {decimal(m['brier'])} | "
            f"{pct(m['high_confidence_accuracy'])}; {m['high_confidence_n']} |"
        )
    lines += [
        "",
        "Four-option random baseline: 25%. Full-set labels are balanced within each main "
        "task (six per label); the fixed-label baseline is also 25%. Smoke is not necessarily "
        "label-balanced. Accuracy excludes invalid/missing responses; coverage is explicit. "
        "High confidence means returned confidence ≥0.8, not a guarantee.",
        "",
        "## Both tasks on the same excerpt",
        "",
        f"Complete pairs: {p['complete']}/{p['planned']}. Both correct: {p['both_correct']} "
        f"({pct(p['both_correct_rate'])} of complete pairs; "
        f"{pct(p['both_correct_planned_rate'])} of all planned pairs). "
        f"Paraphrase only: {p['paraphrase_only']}; application only: {p['application_only']}; "
        f"neither: {p['neither_correct']}.",
        "",
        "## Application controls — matched complete pairs only",
        "",
        "Only the state changes. The application instruction, options, option order, and key "
        "stay fixed; question IDs differ. Prose supplies the author's interpretation, not an "
        "independent answer-free normalization. No-poem removes the passage entirely.",
        "",
        "| Control | Matched / planned | Original poem | Control | Control minus poem | "
        "Corrected / regressed |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, m in metrics["controls"].items():
        lines.append(
            f"| {name} | {m['complete_pairs']} / {m['planned']} | "
            f"{pct(m['poem']['accuracy'])} | {pct(m['control']['accuracy'])} | "
            f"{pct(m['accuracy_difference'])} | {m['corrected']} / {m['regressed']} |"
        )
    lines += [
        "",
        "Prose improvement is consistent with difficulty extracting the intended meaning, "
        "but can also reflect simplification or author cues. No-poem success flags answer-only "
        "shortcuts; it is not evidence of poetry understanding. Each four-situation bank is "
        "shared by four excerpts with different correct answers, limiting generic preference "
        "for one situation. These are correlated diagnostics, not extra independent test items.",
        "",
        "## Excerpt audit",
        "",
        "Cells are predicted/expected labels; `invalid` and `unfinished` are not counted correct. "
        "Full choices, rationales, source URLs, probabilities, and failures are in "
        "`answers.jsonl`.",
        "",
        "| Excerpt | Poet | Paraphrase | Application | Prose control | No-poem control |",
        "|---|---|---|---|---|---|",
    ]
    groups = defaultdict(dict)
    for row in rows:
        key = row["category"] if row["phase"] in {"main", "smoke"} else row["phase"]
        groups[row["source"]["excerpt_id"]][key] = row
    for eid, group in sorted(groups.items()):
        cells = []
        for key in ("paraphrase", "application", "prose_control", "no_poem_control"):
            row = group.get(key)
            if row is None:
                cells.append("—")
            elif row["status"] == "ok":
                cells.append(f"{row['metrics']['predicted']}/{row['gold']['expected']}")
            else:
                cells.append("unfinished" if row["status"] == "not_completed" else "invalid")
        source = next(iter(group.values()))["source"]
        lines.append(f"| [{eid}]({source['url']}) | {source['poet']} | " + " | ".join(cells) + " |")
    lines += ["", "## Incorrect or incomplete main questions", ""]
    failed = [
        r
        for r in rows
        if r["phase"] in {"main", "smoke"} and (r["status"] != "ok" or not r["metrics"]["correct"])
    ]
    if not failed:
        lines.append("None.")
    for row in failed:
        lines += [
            "",
            f"### {row['question_id']} — {row['category']}",
            "",
            clean(row["state"]["text"].replace("\n", " / ")),
            "",
        ]
        lines += [
            f"- {label}: {clean(text)}" for label, text in row["question"]["criteria"].items()
        ]
        observed = (
            json.dumps(row["answer"], ensure_ascii=False) if row["status"] == "ok" else row["error"]
        )
        lines += [
            "",
            f"Expected: {row['gold']['expected']}. Observed: {clean(observed)}.",
            f"Rationale: {clean(row['gold']['rationale'])}",
        ]
    usage, latency = summary["usage"], summary["latency_seconds"]
    lines += [
        "",
        "## Resources",
        "",
        f"Request time: {latency['total']:.3f}s total; {decimal(latency['median'])}s median. "
        f"Reported tokens: {usage['input_tokens']} input, {usage['output_tokens']} output. "
        f"Usage present for {usage['requests_with_usage']}/{c['finished_requests']} requests.",
        "",
        "## Interpretation limits",
        "",
        meta["dataset_manifest"]["annotation"],
        "",
        "This pilot has 24 deliberately selected excerpts, six per poet, often familiar and "
        "didactic; several come from the same source section. It tests selected local meanings, "
        "not exhaustive mystical interpretation, complete poems, or representative per-poet "
        "ability. Source pages verify wording/attribution, not the authored answer keys. "
        "Ganjoor AI glosses and reader comments are not used as gold. Situations and modern "
        "prose were authored by the same assistant, so shared framing can make transfer easier. "
        "The eight-question smoke set is a subset, not a holdout, and is never added to full "
        "scores. Nothing is selected or revised using Jev outcomes. Independent Persian-literature "
        "review is needed before treating this as a validated benchmark.",
        "",
    ]
    for warning in summary["warnings"]:
        lines += [f"Warning: {warning}", ""]
    return "\n".join(lines)
