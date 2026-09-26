import copy
import json
import runpy
import shutil
from collections import Counter
from pathlib import Path

import httpx2
import pytest
from test_benchmark import client_for, synthetic_response

from jev_benchmark.cli import main
from jev_benchmark.data import THRESHOLDS, load_dataset, payload
from jev_benchmark.poetry import validate_poetry_cases
from jev_benchmark.report import build_report
from jev_benchmark.runner import plan_jobs, run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "poetry"
PREPARATION = runpy.run_path(str(ROOT / "scripts" / "prepare_poetry.py"))


@pytest.fixture
def poetry():
    return load_dataset(DATA)


def test_preparation_is_reproducible_and_self_contained(tmp_path):
    target = tmp_path / "poetry"
    shutil.copytree(DATA / "source", target / "source")
    shutil.copyfile(DATA / "review.json", target / "review.json")
    manifest = PREPARATION["prepare"](target)
    assert manifest["thresholds"] == THRESHOLDS
    assert manifest["preparation"]["source_questions"] == 586
    assert manifest["preparation"]["excluded_questions"] == 26
    assert manifest["preparation"]["unused_answer_keys"] == 914
    assert manifest["counts"] == {"choice": 560}
    for name in list(manifest["sha256"]) + ["manifest.json"]:
        assert (target / name).read_bytes() == (DATA / name).read_bytes()
    assert PREPARATION["prepare"](target, check=True) == manifest


def test_preparation_refuses_silent_revision_change(tmp_path):
    target = tmp_path / "poetry"
    shutil.copytree(DATA, target)
    review = json.loads((target / "review.json").read_text())
    review["excluded"]["36"] = "New reviewed exclusion"
    (target / "review.json").write_text(json.dumps(review, ensure_ascii=False))
    before = (target / "scenarios.jsonl").read_bytes()
    with pytest.raises(ValueError, match="Frozen revision changed"):
        PREPARATION["prepare"](target)
    assert (target / "scenarios.jsonl").read_bytes() == before


def test_preparation_requires_valid_sources_and_repairs():
    source = json.loads((DATA / "source/questions-outliers.json").read_text())
    keys = json.loads((DATA / "source/answer_keys.json").read_text())
    legacy = json.loads((DATA / "source/legacy-41.json").read_text())
    review = json.loads((DATA / "review.json").read_text())
    del keys["6"]
    with pytest.raises(ValueError, match="Missing/invalid answer key: 6"):
        PREPARATION["compile_dataset"](source, keys, legacy, review)
    keys["6"] = 1
    review["replacements"][0]["before"] = "different source text"
    with pytest.raises(ValueError, match="Replacement precondition differs: 920"):
        PREPARATION["compile_dataset"](source, keys, legacy, review)


def test_preserves_stems_keys_and_supported_repairs(poetry):
    by_id = {s["source"]["question_id"]: s for s in poetry.scenarios}
    raw = json.loads((DATA / "source/questions-outliers.json").read_text())
    source = {q["id"]: q for p in raw["pages"] for q in p["data"]["questions"]}
    keys = json.loads((DATA / "source/answer_keys.json").read_text())
    review = json.loads((DATA / "review.json").read_text())
    assert set(source) - set(by_id) == {int(k) for k in review["excluded"]}
    for source_id, scenario in by_id.items():
        qid = scenario["questions"][0]["id"]
        assert poetry.gold[qid]["expected"] == "ABCD"[keys[str(source_id)] - 1]
        if source_id not in {1321, 1323}:
            assert scenario["state"]["text"] == source[source_id]["stem"]
    first = by_id[6]["questions"][0]["criteria"]["A"]
    assert first == "طریق عشق پرآشوب و فتنه است ای دل\nبیفتد آن که در این راه با شتاب رود"
    assert by_id[227]["questions"][0]["criteria"]["A"] == "افتادگی"
    assert "جوشش عشق است کاندر می فتاد" in by_id[1321]["state"]["text"]
    assert not by_id[93]["questions"][0]["criteria"]["B"].splitlines()[0].endswith("2")
    assert not by_id[920]["questions"][0]["criteria"]["D"].endswith("921")


def test_smoke_is_balanced_fixed_subset_and_full_has_no_diagnostics(poetry):
    assert Counter(g["expected"] for g in poetry.smoke_gold.values()) == dict.fromkeys("ABCD", 3)
    expected = set()
    for label in "ABCD":
        group = [
            s for s in poetry.scenarios if poetry.gold[s["questions"][0]["id"]]["expected"] == label
        ]
        expected.update(group[i]["id"] for i in (0, len(group) // 2, len(group) - 1))
    assert {s["id"] for s in poetry.smoke} == expected
    jobs = plan_jobs(poetry, "full", "jev-1.13.0")
    assert len(jobs) == 560
    assert {j["phase"] for j in jobs} == {"main"}
    assert all(len(j["request"]["questions"]) == 1 for j in jobs)
    assert len(plan_jobs(poetry, "smoke", "jev-1.13.0")) == 12


@pytest.mark.parametrize(
    "filename", ["gold.jsonl", "source/questions-outliers.json", "review.json"]
)
def test_frozen_inputs_cannot_be_changed_silently(tmp_path, filename):
    target = tmp_path / "poetry"
    shutil.copytree(DATA, target)
    path = target / filename
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_dataset(target)


@pytest.mark.parametrize(
    "mutation, match",
    [
        (lambda s, g: s.append(s[0]), "Duplicate source ID"),
        (lambda s, g: g.pop(), "question/gold IDs differ"),
        (lambda s, g: g[0].update(expected="AB"), "Invalid Choice gold"),
        (lambda s, g: s[0]["questions"][0].update(expected="A"), "question fields"),
        (lambda s, g: s[0]["state"].update(expected="A"), "Invalid poetry state"),
        (lambda s, g: s[0]["questions"][0].update(type="noul"), "Choice only"),
        (lambda s, g: s[0]["questions"].append(s[0]["questions"][0]), "one question"),
        (lambda s, g: s[0]["source"].update(page=0), "Invalid poetry source"),
    ],
)
def test_poetry_validation_failures(poetry, mutation, match):
    scenarios, gold = copy.deepcopy(poetry.scenarios), copy.deepcopy(list(poetry.gold.values()))
    mutation(scenarios, gold)
    with pytest.raises(ValueError, match=match):
        validate_poetry_cases(scenarios, gold)


def test_reversed_duplicate_options_are_rejected(poetry):
    scenarios = copy.deepcopy(poetry.scenarios)
    criteria = scenarios[0]["questions"][0]["criteria"]
    criteria["B"] = "\n".join(reversed(criteria["A"].splitlines()))
    with pytest.raises(ValueError, match="Duplicate poetry options"):
        validate_poetry_cases(scenarios, list(poetry.gold.values()))


def test_payload_has_reference_passage_but_no_gold_or_metadata(poetry):
    scenario = copy.deepcopy(
        next(s for s in poetry.scenarios if s["source"]["question_id"] == 1283)
    )
    scenario.update(gold="NEVER_SEND")
    scenario["questions"][0].update(expected="NEVER_SEND", rationale="NEVER_SEND")
    request = payload(scenario, "jev-1.13.0")
    assert request["state"]["text"] == scenario["state"]["text"]
    assert "پانزده" in request["state"]["text"]
    assert len(request["questions"]["p1283q1"]["criteria"]) == 4
    wire = json.dumps(request, ensure_ascii=False)
    for marker in ["NEVER_SEND", "source", "question_id", "page", "gold", "rationale", "category"]:
        assert marker not in wire


def test_sdk_run_metrics_failures_and_offline_reproduction(poetry, tmp_path):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert len(body["questions"]) == 1
        qid = next(iter(body["questions"]))
        answer = synthetic_response(body, poetry)
        if len(calls) == 2:
            wrong = next(k for k in "ABCD" if k != poetry.gold[qid]["expected"])
            answer["answers"][qid].update(
                choice=wrong, probabilities={k: float(k == wrong) for k in "ABCD"}
            )
        elif len(calls) == 3:
            answer["answers"].pop(qid)
        elif len(calls) == 4:
            answer["answers"][qid]["probabilities"] = dict.fromkeys("ABCD", 0.8)
        return httpx2.Response(200, json=answer)

    output = tmp_path / "run"
    with client_for(handler) as client:
        run(poetry, output, suite="smoke", client=client)
    summary = build_report(output)
    assert len(calls) == 12
    assert summary["completion"]["valid_answers"] == 10
    assert summary["completion"]["failed_answers"] == 2
    assert summary["main"]["choice"]["accuracy"] == 0.9
    assert summary["main"]["choice"]["brier"] == pytest.approx(0.2)
    assert summary["baselines"]["majority_accuracy"] == 0.25
    report = (output / "report.md").read_text()
    assert "9 correct / 10 valid / 12 planned" in report
    assert "INCOMPLETE" in report
    assert "source question" in report and "A (source 1)" in report
    for irrelevant in ["Noul precision", "Matched pairs", "English counterparts", "Repeatability"]:
        assert irrelevant not in report
    before = {
        name: (output / name).read_bytes()
        for name in ("summary.json", "answers.jsonl", "report.md")
    }
    assert main(["report", str(output)]) == 2
    assert before == {name: (output / name).read_bytes() for name in before}


def test_complete_full_poetry_run_and_cli_validation(poetry, tmp_path, capsys):
    def handler(request):
        return httpx2.Response(200, json=synthetic_response(json.loads(request.content), poetry))

    with client_for(handler) as client:
        run(poetry, tmp_path / "full", client=client)
    summary = build_report(tmp_path / "full")
    assert summary["completion"]["complete"]
    assert summary["completion"]["valid_answers"] == 560
    assert summary["main"]["choice"]["accuracy"] == 1.0
    counts = Counter(g["expected"] for g in poetry.gold.values())
    assert summary["baselines"]["majority_accuracy"] == max(counts.values()) / 560
    assert main(["validate", "--data", str(DATA)]) == 0
    assert "560 main questions" in capsys.readouterr().out
    assert main(["report", str(tmp_path / "full")]) == 0
