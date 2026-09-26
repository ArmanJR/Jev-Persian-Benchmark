import copy
import json
import runpy
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import httpx2
import pytest
from test_benchmark import client_for, synthetic_response

from jev_benchmark.classical import validate_classical_cases
from jev_benchmark.cli import main
from jev_benchmark.data import load_dataset, payload
from jev_benchmark.report import build_report
from jev_benchmark.runner import plan_jobs, run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "classical"
PREP = runpy.run_path(str(ROOT / "scripts" / "prepare_classical.py"))


@pytest.fixture
def classical():
    return load_dataset(DATA)


def test_reproducible_offline_preparation(tmp_path):
    for name in ("authored.json", "sources.json"):
        shutil.copyfile(DATA / name, tmp_path / name)
    manifest = PREP["prepare"](tmp_path)
    for name in [*manifest["sha256"], "manifest.json"]:
        assert (tmp_path / name).read_bytes() == (DATA / name).read_bytes()
    assert PREP["prepare"](tmp_path, check=True) == manifest


def test_source_parser_ignores_glosses_and_comments():
    markup = '<div class="m1"><p>اول &amp; دوم</p></div>'
    markup += '<div class="m2"><p><b>سوم</b></p></div>'
    markup += '<div class="meaning"><p>AI GLOSS</p></div><p>USER COMMENT</p>'
    assert PREP["parse_verses"](markup) == ["اول & دوم", "سوم"]


def test_frozen_revision_cannot_be_silently_reauthored(tmp_path):
    shutil.copytree(DATA, tmp_path / "data")
    target = tmp_path / "data"
    authored = json.loads((target / "authored.json").read_text())
    authored["excerpts"][0]["paraphrase"]["rationale"] += " Additional review."
    (target / "authored.json").write_text(json.dumps(authored, ensure_ascii=False))
    before = (target / "gold.jsonl").read_bytes()
    with pytest.raises(ValueError, match="Frozen revision changed"):
        PREP["prepare"](target)
    assert (target / "gold.jsonl").read_bytes() == before
    authored["revision"] = "1.0.1"
    (target / "authored.json").write_text(json.dumps(authored, ensure_ascii=False))
    assert PREP["prepare"](target)["revision"] == "1.0.1"


def test_source_wording_and_selection_are_verified():
    authored = json.loads((DATA / "authored.json").read_text())
    sources = json.loads((DATA / "sources.json").read_text())
    authored["excerpts"][0]["verified_text"] += " fabricated"
    with pytest.raises(ValueError, match="quotation differs"):
        PREP["compile_dataset"](authored, sources)


@pytest.mark.parametrize("name", ["authored.json", "sources.json", "scenarios.jsonl", "gold.jsonl"])
def test_frozen_hashes_cover_all_inputs(tmp_path, name):
    shutil.copytree(DATA, tmp_path / "data")
    path = tmp_path / "data" / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_dataset(tmp_path / "data")


def test_independent_requests_and_matched_controls(classical):
    jobs = plan_jobs(classical, "full", "jev-1.13.0")
    assert len(jobs) == 96
    assert Counter(j["phase"] for j in jobs) == {
        "main": 48,
        "prose_control": 24,
        "no_poem_control": 24,
    }
    assert len(plan_jobs(classical, "smoke", "jev-1.13.0")) == 8
    groups = defaultdict(dict)
    for job in jobs:
        s = job["scenario"]
        assert len(job["request"]["questions"]) == 1
        groups[s["source"]["excerpt_id"]][s["id"][-1]] = job["request"]
    for group in groups.values():
        assert group["p"]["state"] == group["a"]["state"]
        for key in ("c", "n"):
            assert group[key]["state"] != group["a"]["state"]
            assert list(group[key]["questions"].values()) == list(group["a"]["questions"].values())
        assert group["n"]["state"]["text"] == PREP["NO_POEM"]
        assert list(group["a"]["questions"].values()) != list(group["p"]["questions"].values())


def test_labels_balanced_and_shared_banks_do_not_reward_one_generic_situation(classical):
    banks = defaultdict(list)
    for s in classical.scenarios:
        q = s["questions"][0]
        if s["category"] == "application":
            banks[tuple(q["criteria"].items())].append(classical.gold[q["id"]]["expected"])
    assert len(banks) == 6
    assert all(Counter(labels) == dict.fromkeys("ABCD", 1) for labels in banks.values())
    for task in ("paraphrase", "application"):
        assert Counter(
            classical.gold[s["questions"][0]["id"]]["expected"]
            for s in classical.scenarios
            if s["category"] == task
        ) == dict.fromkeys("ABCD", 6)


def test_payload_excludes_gold_source_and_other_task(classical):
    s = copy.deepcopy(classical.scenarios[1])
    s["gold"] = s["questions"][0]["rationale"] = "SECRET_ANNOTATION"
    request = payload(s, "jev-1.13.0")
    assert set(request) == {"model", "state", "questions"}
    assert set(request["state"]) == {"text"}
    assert set(next(iter(request["questions"].values()))) == {"type", "instructions", "criteria"}
    wire = json.dumps(request, ensure_ascii=False)
    for forbidden in ("SECRET_ANNOTATION", "ganjoor.net", "compassion", "saadi", "paraphrase"):
        assert forbidden not in wire


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda s, g: s.append(copy.deepcopy(s[0])), "Duplicate classical scenario"),
        (lambda s, g: g.pop(), "question/gold IDs differ"),
        (lambda s, g: s[0]["state"].update(gold="A"), "Invalid classical state"),
        (lambda s, g: s[0]["questions"].append(copy.deepcopy(s[0]["questions"][0])), "independent"),
        (
            lambda s, g: s[2]["questions"][0]["criteria"].update(A="different"),
            "Control question/options differ",
        ),
        (lambda s, g: s[3]["state"].update(text="The answer is A"), "No-poem control"),
        (lambda s, g: s[0].update(condition="prose_control"), "Invalid task/condition"),
    ],
)
def test_validation_rejects_leakage_and_broken_pairs(classical, mutation, message):
    scenarios = sorted(
        copy.deepcopy(classical.scenarios + classical.diagnostics),
        key=lambda s: (s["source"]["excerpt_id"], "pacn".index(s["id"][-1])),
    )
    gold = copy.deepcopy(list(classical.gold.values()))
    mutation(scenarios, gold)
    with pytest.raises(ValueError, match=message):
        validate_classical_cases(scenarios, gold)


def test_full_sdk_run_control_metrics_and_offline_reproduction(classical, tmp_path, capsys):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        response = synthetic_response(body, classical)
        qid = next(iter(body["questions"]))
        if qid in {"c001aq1", "c002pq1", "c003cq1"}:
            wrong = next(k for k in "ABCD" if k != classical.gold[qid]["expected"])
            response["answers"][qid].update(
                choice=wrong, probabilities={k: float(k == wrong) for k in "ABCD"}
            )
        if qid in {"c004aq1", "c005cq1"}:
            response["answers"].pop(qid)
        return httpx2.Response(200, json=response)

    with client_for(handler) as client:
        run(classical, tmp_path / "full", client=client)
    summary = build_report(tmp_path / "full")
    assert len(calls) == 96
    assert summary["completion"]["valid_answers"] == 94
    assert summary["main"]["choice"]["planned"] == 48
    assert summary["categories"]["application"]["choice"]["correct"] == 22
    pairs = summary["classical"]["paired_tasks"]
    assert pairs["planned"] == 24 and pairs["complete"] == 23
    assert pairs["both_correct"] == 21
    assert pairs["paraphrase_only"] == 1 and pairs["application_only"] == 1
    prose = summary["classical"]["controls"]["prose_control"]
    assert prose["complete_pairs"] == 22
    assert prose["corrected"] == prose["regressed"] == 1
    assert prose["accuracy_difference"] == 0
    blank = summary["classical"]["controls"]["no_poem_control"]
    assert blank["corrected"] == 1 and blank["regressed"] == 0
    assert blank["accuracy_difference"] == pytest.approx(1 / 23)
    report = (tmp_path / "full/report.md").read_text()
    assert "INCOMPLETE" in report and "Prose control" in report
    assert "Complete pairs: 23/24. Both correct: 21" in report
    assert "Source pages verify wording/attribution, not the authored answer keys." in report
    assert "Expected:" in report and "Rationale:" in report
    before = {
        name: (tmp_path / "full" / name).read_bytes()
        for name in ("summary.json", "answers.jsonl", "report.md")
    }
    assert main(["report", str(tmp_path / "full")]) == 2
    assert before == {name: (tmp_path / "full" / name).read_bytes() for name in before}
    assert main(["validate", "--data", str(DATA)]) == 0
    assert "48 main questions, 24 prose_control" in capsys.readouterr().out


def test_smoke_has_no_controls_and_succeeds(classical, tmp_path):
    def handler(request):
        return httpx2.Response(200, json=synthetic_response(json.loads(request.content), classical))

    with client_for(handler) as client:
        run(classical, tmp_path / "smoke", suite="smoke", client=client)
    summary = build_report(tmp_path / "smoke")
    assert summary["completion"]["complete"]
    assert summary["main"]["choice"]["correct"] == 8
    assert summary["classical"]["paired_tasks"]["both_correct"] == 4
    for value in summary["classical"]["controls"].values():
        assert value["planned"] == 0 and value["accuracy_difference"] is None
    assert main(["report", str(tmp_path / "smoke")]) == 0
