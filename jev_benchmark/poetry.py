"""Validation for the separately frozen, Choice-only literary question bank."""

import hashlib
import re
import unicodedata
from collections import Counter

from .data import Dataset, read_jsonl, require

FROZEN_FILES = {
    "scenarios.jsonl",
    "gold.jsonl",
    "review.json",
    "source/questions-outliers.json",
    "source/answer_keys.json",
    "source/legacy-41.json",
}


def option_signature(text):
    """Catch duplicated verses even when their halves have been reversed."""
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans("يك", "یک"))
    return tuple(sorted(re.sub(r"[\W_]+", "", line) for line in text.splitlines()))


def validate_poetry_cases(scenarios, gold_rows):
    require(bool(scenarios), "Empty poetry dataset")
    gold, question_ids, source_ids = {}, set(), set()
    for row in gold_rows:
        require(set(row) == {"id", "expected"}, "Invalid poetry gold fields")
        require(isinstance(row["id"], str) and row["id"] not in gold, "Duplicate/invalid gold ID")
        require(
            isinstance(row["expected"], str) and row["expected"] in list("ABCD"),
            "Invalid Choice gold",
        )
        gold[row["id"]] = row
    for scenario in scenarios:
        require(
            set(scenario) == {"id", "category", "tags", "source", "state", "questions"},
            "Invalid poetry scenario fields",
        )
        source = scenario["source"]
        require(
            isinstance(source, dict)
            and set(source) == {"question_id", "page"}
            and all(type(v) is int and v > 0 for v in source.values()),
            "Invalid poetry source",
        )
        source_id = source["question_id"]
        require(source_id not in source_ids, f"Duplicate source ID: {source_id}")
        source_ids.add(source_id)
        require(scenario["id"] == f"p{source_id:04d}", "Source/scenario ID mismatch")
        require(
            scenario["category"] == "literary_semantics"
            and scenario["tags"] == ["persian_literature"],
            "Invalid poetry category/tags",
        )
        state = scenario["state"]
        require(
            isinstance(state, dict)
            and set(state) == {"text"}
            and isinstance(state["text"], str)
            and state["text"].strip(),
            "Invalid poetry state",
        )
        require(
            isinstance(scenario["questions"], list) and len(scenario["questions"]) == 1,
            "Poetry requires one question per scenario",
        )
        q = scenario["questions"][0]
        require(
            isinstance(q, dict) and set(q) == {"id", "type", "instructions", "criteria"},
            "Invalid poetry question fields",
        )
        qid = q["id"]
        require(
            qid == scenario["id"] + "q1" and qid not in question_ids,
            "Duplicate/invalid question ID",
        )
        question_ids.add(qid)
        require(q["type"] == "choice", "Poetry supports Choice only")
        require(
            isinstance(q["instructions"], str) and q["instructions"].strip(), "Empty instructions"
        )
        options = q["criteria"]
        require(
            isinstance(options, dict)
            and list(options) == list("ABCD")
            and all(isinstance(v, str) and v.strip() for v in options.values()),
            "Invalid poetry options",
        )
        require(
            len({option_signature(v) for v in options.values()}) == 4,
            f"Duplicate poetry options: {qid}",
        )
        require(
            not any("تضمین بیت را اینجا وارد کنید" in v for v in options.values()),
            f"Placeholder option: {qid}",
        )
    require(gold.keys() == question_ids, "Poetry question/gold IDs differ")
    return gold


def load_poetry_dataset(root, manifest):
    require(set(manifest["sha256"]) == FROZEN_FILES, "Invalid poetry frozen file list")
    for name, digest in manifest["sha256"].items():
        require(
            hashlib.sha256((root / name).read_bytes()).hexdigest() == digest,
            f"Frozen dataset hash mismatch: {name}; create a documented revision",
        )
    scenarios = read_jsonl(root / "scenarios.jsonl")
    gold = validate_poetry_cases(scenarios, read_jsonl(root / "gold.jsonl"))
    require(manifest["counts"] == {"choice": len(gold)}, "Poetry counts do not match manifest")
    require(
        manifest["label_counts"] == dict(Counter(g["expected"] for g in gold.values())),
        "Poetry label counts do not match manifest",
    )
    stats = manifest["preparation"]
    require(
        stats["retained_questions"] == len(gold)
        and stats["source_questions"] == len(gold) + stats["excluded_questions"],
        "Invalid poetry preparation counts",
    )
    require(manifest["repeat_scenarios"] == [], "Poetry has no repeat phase")
    smoke_ids = manifest["smoke_scenarios"]
    by_id = {s["id"]: s for s in scenarios}
    require(
        isinstance(smoke_ids, list)
        and len(smoke_ids) == 12
        and all(isinstance(s, str) and s in by_id for s in smoke_ids)
        and len(set(smoke_ids)) == 12,
        "Invalid poetry smoke subset",
    )
    smoke = [by_id[s] for s in smoke_ids]
    smoke_gold = {s["questions"][0]["id"]: gold[s["questions"][0]["id"]] for s in smoke}
    require(
        Counter(g["expected"] for g in smoke_gold.values()) == dict.fromkeys("ABCD", 3),
        "Poetry smoke labels unbalanced",
    )
    return Dataset(scenarios, gold, [], manifest, smoke, smoke_gold)
