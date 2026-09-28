import copy
import json
from pathlib import Path

import httpx2
import pytest
from typesafe_sdk import RetryPolicy, TypeSafeClient

from jev_benchmark.cli import main
from jev_benchmark.data import THRESHOLDS, load_dataset, payload, validate_cases
from jev_benchmark.report import analyze, build_report, read_events
from jev_benchmark.runner import SCORING_VERSION, local_api_url, plan_jobs, run
from jev_benchmark.scoring import score_answer, summarize

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def dataset():
    return load_dataset(ROOT / "data")


def synthetic_response(request, dataset, *, omitted=(), model="jev-1.13.0"):
    answers = {}
    all_gold = dataset.gold | dataset.smoke_gold
    for qid, q in request["questions"].items():
        if qid in omitted:
            continue
        gold = all_gold[qid]["expected"]
        if q["type"] == "noul":
            answer = {"type": "noul", "noul": float(gold)}
        elif q["type"] == "choice":
            answer = {
                "type": "choice",
                "choice": gold,
                "confidence": 1.0,
                "probabilities": {k: float(k == gold) for k in q["criteria"]},
            }
        else:
            answer = {
                "type": "score",
                "score": float(gold),
                "confidence": 1.0,
                "legend": {str(i): label for i, label in enumerate(q["criteria"])},
                "probabilities": {str(i): float(i == gold) for i in range(len(q["criteria"]))},
            }
        answers[qid] = answer
    return {"model": model, "usage": {"input_tokens": 20, "output_tokens": 6}, "answers": answers}


def client_for(handler):
    return TypeSafeClient(
        api_key="test-key",
        transport=httpx2.MockTransport(handler),
        retry=RetryPolicy(max_retries=0),
    )


def test_dataset_counts_and_unicode(dataset):
    assert len(dataset.scenarios) == 80
    assert len(dataset.gold) == 480
    assert len(dataset.smoke_gold) == 12
    assert len(dataset.pairs) == 48
    text = "\n".join(s["state"]["text"] for s in dataset.scenarios)
    for marker in ["\u200c", "ي", "ك", "۲۵۰", "500", "لطفن", "delivery", "ramze"]:
        assert marker in text
    encoded = json.dumps(payload(dataset.scenarios[0], "jev-1.13.0"), ensure_ascii=False)
    assert json.loads(encoded)["state"] == dataset.scenarios[0]["state"]


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda s, g: s[1].update(id=s[0]["id"]), "Duplicate/invalid scenario"),
        (
            lambda s, g: s[0]["questions"][1].update(id=s[0]["questions"][0]["id"]),
            "Duplicate/invalid question",
        ),
        (lambda s, g: g[0].update(expected="Z"), "Invalid Choice gold"),
        (lambda s, g: g[3].update(expected=1), "Invalid Noul"),
        (lambda s, g: g[5].update(expected=3), "Invalid Score"),
        (lambda s, g: g[0].update(rationale=""), "Missing rationale"),
        (
            lambda s, g: s[0]["questions"][0]["english"].update(criteria={"Z": "bad"}),
            "English options",
        ),
        (lambda s, g: g.pop(), "Missing gold"),
        (lambda s, g: s[0]["questions"][0].update(expected="A"), "Invalid question fields"),
    ],
)
def test_validation_failures(dataset, mutation, match):
    scenarios, gold = copy.deepcopy(dataset.scenarios), copy.deepcopy(list(dataset.gold.values()))
    mutation(scenarios, gold)
    with pytest.raises(ValueError, match=match):
        validate_cases(scenarios, gold)


def test_frozen_hash_catches_edit(dataset, tmp_path):
    for source in (ROOT / "data").glob("*.json*"):
        (tmp_path / source.name).write_bytes(source.read_bytes())
    with (tmp_path / "gold.jsonl").open("a") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_dataset(tmp_path)


def test_payload_excludes_gold_and_batches(dataset):
    scenario = copy.deepcopy(dataset.scenarios[0])
    scenario["gold"] = "NEVER_SEND"
    for q in scenario["questions"]:
        q.update(expected="NEVER_SEND", rationale="NEVER_SEND")
    p = payload(scenario, "model")
    assert len(p["questions"]) == 6
    assert set(p) == {"state", "questions", "model"}
    wire = json.dumps(p)
    for word in ["NEVER_SEND", "rationale", "expected", "tags", "category", "english"]:
        assert word not in wire


def test_job_counts_repeat_payloads_and_english_alignment(dataset):
    jobs = plan_jobs(dataset, "full", "jev-1.13.0")
    assert len(jobs) == 106
    assert sum(len(j["scenario"]["questions"]) for j in jobs) == 624
    main_jobs = {j["scenario"]["id"]: j for j in jobs if j["phase"] == "main"}
    for j in jobs:
        base = main_jobs[j["scenario"]["id"]]
        if j["phase"] == "repeat":
            assert j["request"] == base["request"]
            assert j["gold"] == base["gold"]
        elif j["phase"] == "english":
            assert j["request"]["state"] == base["request"]["state"]
            for qid, q in j["request"]["questions"].items():
                assert j["gold"][qid] == base["gold"][qid]
                if q["type"] == "choice":
                    assert list(q["criteria"]) == list(
                        base["request"]["questions"][qid]["criteria"]
                    )
    assert sum(len(j["scenario"]["questions"]) for j in plan_jobs(dataset, "smoke", "m")) == 12


@pytest.mark.parametrize(
    "p,pred,high",
    [
        (0, False, True),
        (0.2, False, True),
        (0.20001, False, False),
        (0.49999, False, False),
        (0.5, True, False),
        (0.79999, True, False),
        (0.8, True, True),
        (1, True, True),
    ],
)
def test_noul_boundaries(p, pred, high):
    result = score_answer({"type": "noul"}, True, {"type": "noul", "noul": p})
    assert result["predicted"] is pred
    assert result["high_confidence"] is high
    assert result["brier"] == pytest.approx((p - 1) ** 2)


def test_choice_brier_and_confidence():
    q = {"type": "choice", "criteria": {"A": "a", "B": "b", "C": "c", "D": "d"}}
    a = {
        "type": "choice",
        "choice": "B",
        "confidence": 0.8,
        "probabilities": {"A": 0.1, "B": 0.6, "C": 0.2, "D": 0.1},
    }
    result = score_answer(q, "A", a)
    assert result["brier"] == pytest.approx(1.22)
    assert not result["correct"]
    assert result["high_confidence"]
    a["confidence"] = 0.79999
    assert not score_answer(q, "A", a)["high_confidence"]


@pytest.mark.parametrize(
    "value,gold,success,decision",
    [
        (0, 0, True, 0),
        (0.5, 1, True, 1),
        (0.4999, 1, False, 0),
        (1.5, 1, True, 2),
        (1.5001, 1, False, 2),
        (2, 0, False, 2),
    ],
)
def test_score_metrics_and_boundaries(value, gold, success, decision):
    q = {"type": "score", "criteria": ["low", "medium", "high"]}
    a = {
        "type": "score",
        "score": value,
        "confidence": 0.8,
        "legend": {"0": "low", "1": "medium", "2": "high"},
        "probabilities": {"0": 1 - value / 2, "1": 0, "2": value / 2},
    }
    result = score_answer(q, gold, a)
    assert result["absolute_error"] == pytest.approx(abs(value - gold))
    assert result["normalized_error"] == pytest.approx(abs(value - gold) / 2)
    assert result["correct"] is success
    assert result["predicted"] == decision


@pytest.mark.parametrize(
    "answer",
    [
        None,
        {},
        {"type": "choice"},
        {"type": "noul", "noul": None},
        {"type": "noul", "noul": "0.5"},
        {"type": "noul", "noul": True},
        {"type": "noul", "noul": float("nan")},
        {"type": "noul", "noul": float("inf")},
        {"type": "noul", "noul": -0.1},
        {"type": "noul", "noul": 1.1},
    ],
)
def test_invalid_answers(answer):
    with pytest.raises(ValueError):
        score_answer({"type": "noul"}, True, answer)


@pytest.mark.parametrize(
    "change",
    [
        {"probabilities": {"A": 0.7, "B": 0.7}},
        {"probabilities": {"A": 1}},
        {"probabilities": {"A": 1.1, "B": -0.1}},
        {"choice": "Z"},
        {"choice": "B"},
        {"confidence": 2},
    ],
)
def test_invalid_choice_distribution(change):
    answer = {
        "type": "choice",
        "choice": "A",
        "confidence": 0.9,
        "probabilities": {"A": 0.9, "B": 0.1},
    } | change
    with pytest.raises(ValueError):
        score_answer({"type": "choice", "criteria": {"A": "a", "B": "b"}}, "A", answer)


@pytest.mark.parametrize(
    "change", [{"score": 1}, {"legend": {"0": "wrong", "1": "b"}}, {"probabilities": {"1": 1}}]
)
def test_invalid_score_distribution(change):
    answer = {
        "type": "score",
        "score": 0,
        "confidence": 0.9,
        "legend": {"0": "a", "1": "b"},
        "probabilities": {"0": 1, "1": 0},
    } | change
    with pytest.raises(ValueError):
        score_answer({"type": "score", "criteria": ["a", "b"]}, 0, answer)


def test_noul_precision_recall_and_failure_accounting():
    rows = []
    for p, gold in [(0.9, True), (0.9, False), (0.1, True), (0.1, False)]:
        rows.append(
            {
                "primitive": "noul",
                "status": "ok",
                "metrics": score_answer({"type": "noul"}, gold, {"type": "noul", "noul": p}),
            }
        )
    rows += [
        {"primitive": "noul", "status": "error"},
        {"primitive": "noul", "status": "not_completed"},
    ]
    m = summarize(rows)["noul"]
    assert (m["planned"], m["valid"], m["failures"], m["not_completed"]) == (6, 4, 1, 1)
    assert m["accuracy"] == m["precision"] == m["recall"] == 0.5
    assert m["brier"] == pytest.approx(0.41)
    assert m["high_confidence_coverage"] == 1
    assert summarize([])["noul"]["precision"] is None
    assert summarize([])["score"]["mae"] is None


def test_sdk_integration_and_offline_reproduction(dataset, tmp_path):
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert "expected" not in request.content.decode()
        return httpx2.Response(
            200,
            json=synthetic_response(body, dataset),
            headers={"x-typesafe-request-id": f"req-{len(requests)}"},
        )

    output = tmp_path / "run"
    with client_for(handler) as client:
        run(dataset, output, suite="smoke", client=client)
    summary = build_report(output)
    assert len(requests) == 2
    assert all(len(r["questions"]) == 6 for r in requests)
    assert summary["completion"]["valid_answers"] == 12
    assert summary["completion"]["complete"]
    assert summary["usage"]["input_tokens"] == 40
    assert summary["main"]["choice"]["accuracy"] == 1
    files = ["summary.json", "report.md", "answers.jsonl"]
    before = {name: (output / name).read_bytes() for name in files}
    assert main(["report", str(output)]) == 0
    assert before == {name: (output / name).read_bytes() for name in files}
    events, _ = read_events(output / "requests.jsonl")
    assert events[1]["request_id"] == "req-1"
    assert events[1]["raw_response_text"]
    assert events[1]["actual_request"]["state"] == dataset.smoke[0]["state"]
    with pytest.raises(FileExistsError):
        run(dataset, output, suite="smoke", client=object())


@pytest.mark.parametrize("cloud_key", [None, "cloud-secret-sentinel"])
def test_local_cli_uses_frozen_payloads_without_cloud_configuration(
    dataset, tmp_path, monkeypatch, cloud_key
):
    if cloud_key is None:
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("TYPESAFE_API_KEY", cloud_key)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://cloud.invalid")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:9999")
    requests, clients = [], []
    model = "jeff-qwen3.5-2b"

    def handler(request):
        requests.append(request)
        return httpx2.Response(
            200,
            json=synthetic_response(json.loads(request.content), dataset, model=model),
            headers={"x-request-id": f"local-{len(requests)}"},
        )

    real_http_client = httpx2.Client

    def http_client(**kwargs):
        assert kwargs["trust_env"] is False
        client = real_http_client(transport=httpx2.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx2, "Client", http_client)
    output = tmp_path / "local"
    assert (
        main(
            [
                "run",
                "--data",
                str(ROOT / "data"),
                "--suite",
                "smoke",
                "--model",
                model,
                "--local-url",
                "http://127.0.0.1:8765/",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert clients[0].is_closed
    assert len(requests) == 2
    for request, job in zip(requests, plan_jobs(dataset, "smoke", model), strict=True):
        assert str(request.url) == "http://127.0.0.1:8765/v1/systemone"
        assert request.headers["authorization"] == "Bearer local-unused"
        body = json.loads(request.content)
        assert body == job["request"]
        for qid, question in body["questions"].items():
            if isinstance(question.get("criteria"), dict):
                assert list(question["criteria"]) == list(
                    job["request"]["questions"][qid]["criteria"]
                )
    meta = json.loads((output / "run.json").read_text())
    assert meta["local_url"] == "http://127.0.0.1:8765"
    events, _ = read_events(output / "requests.jsonl")
    assert events[1]["request_id"] == "local-1"
    summary = build_report(output)
    assert summary["completion"]["valid_answers"] == 12
    assert summary["model_mismatch_requests"] == 0
    before = {name: (output / name).read_bytes() for name in ("summary.json", "report.md")}
    assert main(["report", str(output)]) == 0
    assert all((output / name).read_bytes() == content for name, content in before.items())
    assert "cloud-secret-sentinel" not in (output / "requests.jsonl").read_text()


def test_local_authentication_failure_is_actionable(dataset, tmp_path, monkeypatch):
    real_http_client = httpx2.Client
    transport = httpx2.MockTransport(
        lambda request: httpx2.Response(401, json={}, headers={"x-request-id": "local-error"})
    )
    monkeypatch.setattr(
        httpx2, "Client", lambda **kwargs: real_http_client(transport=transport, **kwargs)
    )
    output = tmp_path / "local"
    run(dataset, output, suite="smoke", model="jeff-qwen3.5-2b", local_url="http://localhost:8765")
    summary = build_report(output)
    assert summary["completion"]["finished_requests"] == 1
    assert summary["completion"]["failed_answers"] == 6
    assert summary["completion"]["not_completed"] == 6
    abort = json.loads((output / "completion.json").read_text())["abort"]
    assert "unauthenticated servers" in abort["message"]
    assert abort["request_id"] == "local-error"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "file:///tmp/server",
        "http://localhost:8765/v1",
        "http://user:password@localhost:8765",
        "http://localhost?key=secret",
        "http://localhost#fragment",
        "http://localhost:not-a-port",
        "http://localhost:65536",
        "http://localhost:0",
        "http://[::1",
        "",
        "http://localhost\n",
    ],
)
def test_invalid_local_url_rejected_before_run_creation(dataset, tmp_path, url):
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="HTTP.*loopback root"):
        run(dataset, output, suite="smoke", local_url=url)
    assert not output.exists()


@pytest.mark.parametrize(
    "url", ["http://localhost:8765", "http://127.0.0.1", "https://[::1]:8765/"]
)
def test_loopback_api_roots(url):
    assert local_api_url(url) == url.rstrip("/")


def test_local_cli_requires_explicit_model_and_rejects_conflicting_client(dataset, tmp_path):
    output = tmp_path / "local"
    assert main(["run", "--local-url", "http://localhost:8765", "--output", str(output)]) == 2
    assert not output.exists()
    with pytest.raises(ValueError, match="either client or local_url"):
        run(dataset, output, client=object(), local_url="http://localhost:8765")
    assert not output.exists()


@pytest.mark.parametrize(
    "status,finished,valid",
    [(401, 1, 0), (403, 1, 0), (404, 1, 0), (400, 1, 0), (422, 1, 0), (500, 2, 6), (429, 2, 6)],
)
def test_abort_configuration_but_continue_request_failures(
    dataset, tmp_path, status, finished, valid, monkeypatch
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-sentinel")
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx2.Response(status, json={"detail": "secret-sentinel"})
        return httpx2.Response(200, json=synthetic_response(json.loads(request.content), dataset))

    with client_for(handler) as client:
        run(dataset, tmp_path / "run", suite="smoke", client=client)
    report = build_report(tmp_path / "run")
    assert len(calls) == finished
    assert report["completion"]["valid_answers"] == valid
    assert report["completion"]["failed_answers"] == 6
    assert report["completion"]["not_completed"] == 12 - valid - 6
    assert "secret-sentinel" not in (tmp_path / "run" / "requests.jsonl").read_text()


def test_missing_answer_invalid_probability_and_model_mismatch(dataset, tmp_path):
    def handler(request):
        body = json.loads(request.content)
        qids = list(body["questions"])
        response = synthetic_response(body, dataset, omitted=[qids[0]], model="different-model")
        response["answers"][qids[3]]["noul"] = 1.5
        return httpx2.Response(200, json=response)

    with client_for(handler) as client:
        run(dataset, tmp_path / "run", suite="smoke", client=client)
    report = build_report(tmp_path / "run")
    assert report["completion"]["valid_answers"] == 8
    assert report["completion"]["failed_answers"] == 4
    assert report["completion"]["failed_requests"] == 0
    assert report["model_mismatch_requests"] == 2


def test_interrupt_preserves_completed_results(dataset, tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return httpx2.Response(200, json=synthetic_response(json.loads(request.content), dataset))

    with client_for(handler) as client:
        run(dataset, tmp_path / "run", suite="smoke", client=client)
    result = build_report(tmp_path / "run")
    assert result["completion"]["valid_answers"] == 6
    assert result["completion"]["not_completed"] == 6
    assert json.loads((tmp_path / "run" / "completion.json").read_text())["interrupted"]


def test_truncated_journal_only_last_line(tmp_path):
    path = tmp_path / "journal"
    path.write_text('{"event":"started"}\n{"ev')
    events, warnings = read_events(path)
    assert len(events) == len(warnings) == 1
    path.write_text('{"ev\n{}\n')
    with pytest.raises(ValueError, match="Corrupt journal"):
        read_events(path)


def test_full_diagnostics_and_paired_denominators(dataset):
    jobs = plan_jobs(dataset, "full", "jev-1.13.0")
    meta = {
        "schema_version": 1,
        "scoring_version": SCORING_VERSION,
        "dataset_manifest": dataset.manifest,
        "jobs": jobs,
        "pairs": dataset.pairs,
        "suite": "full",
        "requested_model": "jev-1.13.0",
    }
    events = []
    for j in jobs:
        response = synthetic_response(j["request"], dataset)
        # First English answer fails, so both comparison denominators must exclude it.
        if j["phase"] == "english" and j["scenario"]["id"] == "s001":
            response["answers"].pop("s001q1")
        # One repeated Noul changes its decision; its range must capture that.
        if j["phase"] == "repeat" and j["scenario"]["id"] == "s017" and j["observation"] == 2:
            response["answers"]["s017q4"]["noul"] = 0.1
        events.append(
            {
                "event": "finished",
                "job_id": j["id"],
                "status": "ok",
                "raw_response": response,
                "elapsed_seconds": 0.1,
                "usage": response["usage"],
            }
        )
    result, _ = analyze(meta, events)
    assert result["completion"]["valid_answers"] == 623
    assert result["main"]["choice"]["valid"] == 240
    assert result["pairs"]["invariant"]["both_correct"] == 24
    assert result["pairs"]["contrast"]["both_correct"] == 24
    assert result["english_comparison"]["complete_pairs"] == 47
    assert result["english_comparison"]["persian"]["choice"]["valid"] == 29
    assert result["english_comparison"]["english"]["choice"]["valid"] == 29
    assert result["repeatability"]["complete_triples"] == 48
    assert result["repeatability"]["decision_changes"] == 1
    repeated = next(r for r in result["repeatability"]["questions"] if r["question_id"] == "s017q4")
    assert repeated["numeric_range"] == pytest.approx(0.9)
    assert THRESHOLDS["score_tolerance"] == 0.5


def test_missing_credentials_record_incomplete_run(dataset, tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    run(dataset, tmp_path / "run", suite="smoke")
    report = build_report(tmp_path / "run")
    assert report["completion"]["not_completed"] == 12
    assert report["completion"]["finished_requests"] == 0
    termination = json.loads((tmp_path / "run" / "completion.json").read_text())
    assert termination["abort"]["type"] == "TypeSafeError"


def test_network_failure_continues(dataset, tmp_path):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            raise httpx2.ConnectError("Connection unavailable", request=request)
        return httpx2.Response(200, json=synthetic_response(json.loads(request.content), dataset))

    with client_for(handler) as client:
        run(dataset, tmp_path / "run", suite="smoke", client=client)
    report = build_report(tmp_path / "run")
    assert report["completion"]["failed_requests"] == 1
    assert report["completion"]["valid_answers"] == 6


def test_nonfinite_response_is_preserved_as_failure(dataset, tmp_path):
    def handler(request):
        response = synthetic_response(json.loads(request.content), dataset)
        qid = next(k for k, a in response["answers"].items() if a["type"] == "noul")
        response["answers"][qid]["noul"] = float("nan")
        return httpx2.Response(
            200, content=json.dumps(response).encode(), headers={"content-type": "application/json"}
        )

    with client_for(handler) as client:
        run(dataset, tmp_path / "run", suite="smoke", client=client)
    report = build_report(tmp_path / "run")
    assert report["completion"]["failed_answers"] >= 2
    assert report["completion"]["finished_requests"] == 2
    assert not report["completion"]["complete"]


def test_score_accepts_independently_rounded_live_response():
    question = {"type": "score", "criteria": ["none", "partial", "complete"]}
    answer = {
        "type": "score",
        "score": 1.99,
        "confidence": 0.99,
        "legend": {"0": "none", "1": "partial", "2": "complete"},
        "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0},
    }
    result = score_answer(question, 2, answer)
    assert result["absolute_error"] == pytest.approx(0.01)
    assert result["numeric"] == 1.99
    assert result["correct"]
    with pytest.raises(ValueError, match="probability-weighted"):
        score_answer(question, 2, answer | {"score": 1.97})


@pytest.mark.parametrize(
    "ps",
    [
        {"A": 0.33, "B": 0.33, "C": 0.33},
        {"A": 0.34, "B": 0.34, "C": 0.33},
    ],
)
def test_rounded_probabilities_use_original_values_for_brier(ps):
    question = {"type": "choice", "criteria": {"A": "a", "B": "b", "C": "c"}}
    answer = {"type": "choice", "choice": "A", "confidence": 0.01, "probabilities": ps}
    result = score_answer(question, "A", answer)
    assert result["brier"] == pytest.approx((ps["A"] - 1) ** 2 + ps["B"] ** 2 + ps["C"] ** 2)
    with pytest.raises(ValueError, match="sum to one"):
        score_answer(question, "A", answer | {"probabilities": {"A": 0.3, "B": 0.3, "C": 0.3}})
