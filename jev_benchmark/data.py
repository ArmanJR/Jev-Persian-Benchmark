"""Frozen dataset loading, validation, and API payload construction."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

AREAS = {
    "intent",
    "sentiment",
    "reading",
    "negation",
    "idioms",
    "pragmatics",
    "scenarios",
    "moderation",
    "semantic",
    "extraction",
}
THRESHOLDS = {"noul": 0.5, "high_confidence": 0.8, "score_tolerance": 0.5}
API_FIELDS = {"type", "instructions", "criteria"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc.msg}") from exc
            require(isinstance(row, dict), f"{path}:{line_no}: expected an object")
            rows.append(row)
    return rows


def payload(scenario, model, english=False):
    """An explicit allowlist prevents metadata and gold from entering the request."""
    questions = {}
    for q in scenario["questions"]:
        source = q["english"] if english else q
        questions[q["id"]] = {k: source[k] for k in API_FIELDS if k in source}
    return {"state": scenario["state"], "questions": questions, "model": model}


def validate_cases(scenarios, gold_rows, *, smoke=False):
    expected_total = 12 if smoke else 480
    require(len(scenarios) == (2 if smoke else 80), "Unexpected scenario count")
    ids, qmap, gold = set(), {}, {}
    for row in gold_rows:
        require(set(row) == {"id", "expected", "rationale"}, "Invalid gold fields")
        require(row["id"] not in gold, f"Duplicate gold ID: {row['id']}")
        require(
            isinstance(row["rationale"], str) and row["rationale"].strip(),
            f"Missing rationale: {row['id']}",
        )
        gold[row["id"]] = row
    for scenario in scenarios:
        require(
            set(scenario) == {"id", "category", "tags", "state", "questions"},
            "Invalid scenario fields",
        )
        sid = scenario["id"]
        require(
            isinstance(sid, str) and sid and sid not in ids, f"Duplicate/invalid scenario: {sid}"
        )
        ids.add(sid)
        require(
            isinstance(scenario["state"], dict)
            and set(scenario["state"]) == {"text"}
            and isinstance(scenario["state"]["text"], str)
            and scenario["state"]["text"].strip(),
            f"Invalid state: {sid}",
        )
        require(
            isinstance(scenario["tags"], list)
            and scenario["tags"]
            and all(isinstance(t, str) and t for t in scenario["tags"])
            and len(set(scenario["tags"])) == len(scenario["tags"]),
            f"Invalid tags: {sid}",
        )
        require(scenario["category"] in ({"smoke"} if smoke else AREAS), f"Invalid area: {sid}")
        require(isinstance(scenario["questions"], list), f"Invalid questions: {sid}")
        for q in scenario["questions"]:
            require(
                isinstance(q, dict)
                and {"id", "type", "instructions"} <= q.keys()
                and q.keys() <= API_FIELDS | {"id", "english"},
                f"Invalid question fields: {sid}",
            )
            qid = q["id"]
            require(
                isinstance(qid, str) and qid.startswith(sid + "q") and qid not in qmap,
                f"Duplicate/invalid question ID: {qid}",
            )
            qmap[qid] = (scenario, q)
            require(qid in gold, f"Missing gold: {qid}")
            require(q["type"] in {"choice", "noul", "score"}, f"Invalid primitive: {qid}")
            require(
                isinstance(q["instructions"], str) and q["instructions"].strip(),
                f"Missing instructions: {qid}",
            )
            g = gold[qid]["expected"]
            if q["type"] == "choice":
                require(
                    isinstance(q.get("criteria"), dict)
                    and list(q["criteria"]) == list("ABCD")
                    and all(isinstance(x, str) and x for x in q["criteria"].values())
                    and len(set(q["criteria"].values())) == 4,
                    f"Invalid options: {qid}",
                )
                require(isinstance(g, str) and g in q["criteria"], f"Invalid Choice gold: {qid}")
            elif q["type"] == "noul":
                require("criteria" not in q and type(g) is bool, f"Invalid Noul gold/schema: {qid}")
            else:
                require(
                    isinstance(q.get("criteria"), list)
                    and len(q["criteria"]) == 3
                    and all(isinstance(x, str) and x for x in q["criteria"])
                    and len(set(q["criteria"])) == 3,
                    f"Invalid rubric: {qid}",
                )
                require(
                    type(g) is int and 0 <= g < len(q["criteria"]), f"Invalid Score gold: {qid}"
                )
            if "english" in q:
                en = q["english"]
                require(
                    isinstance(en, dict)
                    and set(en) == (set(q) & API_FIELDS)
                    and en["type"] == q["type"]
                    and isinstance(en["instructions"], str)
                    and en["instructions"].strip(),
                    f"Invalid English counterpart: {qid}",
                )
                if q["type"] == "choice":
                    require(
                        isinstance(en["criteria"], dict)
                        and list(en["criteria"]) == list(q["criteria"])
                        and all(isinstance(x, str) and x for x in en["criteria"].values()),
                        f"English options misaligned: {qid}",
                    )
                elif q["type"] == "score":
                    require(
                        isinstance(en["criteria"], list)
                        and len(en["criteria"]) == 3
                        and all(isinstance(x, str) and x for x in en["criteria"]),
                        f"English rubric misaligned: {qid}",
                    )
        require(
            Counter(q["type"] for q in scenario["questions"])
            == {"choice": 3, "noul": 2, "score": 1},
            f"Invalid batch composition: {sid}",
        )
    require(len(qmap) == expected_total and gold.keys() == qmap.keys(), "Question/gold IDs differ")
    if not smoke:
        require(
            Counter(s["category"] for s in scenarios) == dict.fromkeys(AREAS, 8),
            "Each area must contain 48 questions",
        )
        require(
            Counter(gold[qid]["expected"] for qid, (_, q) in qmap.items() if q["type"] == "noul")
            == {True: 80, False: 80},
            "Noul labels unbalanced",
        )
        require(
            Counter(gold[qid]["expected"] for qid, (_, q) in qmap.items() if q["type"] == "choice")
            == dict.fromkeys("ABCD", 60),
            "Choice labels unbalanced",
        )
        score_counts = Counter(
            gold[qid]["expected"] for qid, (_, q) in qmap.items() if q["type"] == "score"
        )
        require(
            set(score_counts) == {0, 1, 2} and min(score_counts.values()) >= 20,
            "Score levels insufficiently represented",
        )
        require(
            sum("english" in q for _, q in qmap.values()) == 48, "Expected 48 English questions"
        )
        require(
            {s["category"] for s, q in qmap.values() if "english" in q} == AREAS,
            "English subset must cover all areas",
        )
    return gold, qmap


@dataclass
class Dataset:
    scenarios: list
    gold: dict
    pairs: list
    manifest: dict
    smoke: list
    smoke_gold: dict


def load_dataset(directory):
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["thresholds"] == THRESHOLDS, "Unsupported scoring thresholds")
    required_files = {
        "scenarios.jsonl",
        "gold.jsonl",
        "pairs.json",
        "smoke.jsonl",
        "smoke_gold.jsonl",
    }
    require(set(manifest["sha256"]) == required_files, "Invalid frozen file list")
    for name, digest in manifest["sha256"].items():
        require(
            hashlib.sha256((root / name).read_bytes()).hexdigest() == digest,
            f"Frozen dataset hash mismatch: {name}; create a documented revision",
        )
    scenarios, smoke = read_jsonl(root / "scenarios.jsonl"), read_jsonl(root / "smoke.jsonl")
    gold, qmap = validate_cases(scenarios, read_jsonl(root / "gold.jsonl"))
    smoke_gold, _ = validate_cases(smoke, read_jsonl(root / "smoke_gold.jsonl"), smoke=True)
    require(
        not ({s["state"]["text"] for s in smoke} & {s["state"]["text"] for s in scenarios}),
        "Smoke states overlap main dataset",
    )
    require(
        manifest["counts"] == dict(Counter(q["type"] for _, q in qmap.values())),
        "Primitive counts do not match manifest",
    )
    pairs = json.loads((root / "pairs.json").read_text(encoding="utf-8"))
    require(
        len(pairs) == 48 and Counter(p["kind"] for p in pairs) == {"invariant": 24, "contrast": 24},
        "Invalid pair counts",
    )
    seen, pair_ids = set(), set()
    for pair in pairs:
        require(
            set(pair) == {"id", "kind", "questions"} and pair["id"] not in pair_ids,
            "Duplicate/invalid pair ID",
        )
        pair_ids.add(pair["id"])
        require(len(pair["questions"]) == 2, "Pairs must have two questions")
        a, b = pair["questions"]
        require(
            a in qmap and b in qmap and a != b and a not in seen and b not in seen,
            "Missing/reused pair member",
        )
        seen.update([a, b])
        sa, qa = qmap[a]
        sb, qb = qmap[b]
        require(
            sa["state"] != sb["state"] and sa["category"] == sb["category"], "Invalid paired states"
        )
        require(
            {k: qa[k] for k in API_FIELDS if k in qa} == {k: qb[k] for k in API_FIELDS if k in qb},
            "Paired API questions differ",
        )
        require(
            (gold[a]["expected"] == gold[b]["expected"]) == (pair["kind"] == "invariant"),
            "Pair gold relation is incorrect",
        )
    repeat = manifest["repeat_scenarios"]
    by_id = {s["id"]: s for s in scenarios}
    require(len(repeat) == len(set(repeat)) and all(s in by_id for s in repeat), "Invalid repeats")
    require(sum(len(by_id[s]["questions"]) for s in repeat) == 48, "Expected 48 repeat questions")
    return Dataset(scenarios, gold, pairs, manifest, smoke, smoke_gold)
