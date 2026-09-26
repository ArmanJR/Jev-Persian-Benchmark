"""Validation of the frozen classical meaning/application pilot and its controls."""

import hashlib
from collections import Counter, defaultdict

from .data import Dataset, read_jsonl, require

FROZEN_FILES = {"authored.json", "sources.json", "scenarios.jsonl", "gold.jsonl"}
POETS = {"saadi", "hafez", "rumi", "ferdowsi"}
VARIANTS = {
    "p": ("paraphrase", "poem"),
    "a": ("application", "poem"),
    "c": ("application", "prose_control"),
    "n": ("application", "no_poem_control"),
}


def validate_classical_cases(scenarios, gold_rows):
    gold, groups = {}, defaultdict(dict)
    for row in gold_rows:
        require(set(row) == {"id", "expected", "rationale"}, "Invalid classical gold fields")
        require(isinstance(row["id"], str) and row["id"] not in gold, "Duplicate/invalid gold ID")
        require(row["expected"] in list("ABCD"), "Invalid classical Choice gold")
        require(isinstance(row["rationale"], str) and row["rationale"].strip(), "Missing rationale")
        gold[row["id"]] = row
    question_ids = set()
    for s in scenarios:
        require(
            set(s) == {"id", "category", "condition", "tags", "source", "state", "questions"},
            "Invalid classical scenario fields",
        )
        source = s["source"]
        require(
            isinstance(source, dict)
            and set(source) == {"excerpt_id", "poet", "url", "title", "first_hemistich"},
            "Invalid classical source fields",
        )
        eid, poet = source["excerpt_id"], source["poet"]
        require(
            isinstance(eid, str) and len(eid) == 4 and eid[0] == "c" and eid[1:].isdigit(),
            "Invalid excerpt ID",
        )
        require(
            poet in POETS
            and isinstance(source["url"], str)
            and source["url"].startswith("https://ganjoor.net/")
            and isinstance(source["title"], str)
            and source["title"].strip()
            and type(source["first_hemistich"]) is int
            and source["first_hemistich"] > 0,
            "Invalid classical source",
        )
        sid = s["id"]
        require(
            isinstance(sid, str) and sid[:-1] == eid and sid[-1:] in VARIANTS,
            "Invalid classical scenario ID",
        )
        variant = sid[-1]
        require(variant not in groups[eid], "Duplicate classical scenario")
        groups[eid][variant] = s
        require((s["category"], s["condition"]) == VARIANTS[variant], "Invalid task/condition")
        require(
            isinstance(s["tags"], list)
            and len(s["tags"]) == 2
            and s["tags"][0] == poet
            and isinstance(s["tags"][1], str)
            and s["tags"][1],
            "Invalid classical tags",
        )
        require(
            isinstance(s["state"], dict)
            and set(s["state"]) == {"text"}
            and isinstance(s["state"]["text"], str)
            and s["state"]["text"].strip(),
            "Invalid classical state",
        )
        require(
            isinstance(s["questions"], list) and len(s["questions"]) == 1,
            "Classical tasks require independent one-question requests",
        )
        q = s["questions"][0]
        require(set(q) == {"id", "type", "instructions", "criteria"}, "Invalid question fields")
        require(q["id"] == sid + "q1" and q["id"] not in question_ids, "Invalid question ID")
        question_ids.add(q["id"])
        require(
            q["type"] == "choice"
            and isinstance(q["instructions"], str)
            and q["instructions"].strip(),
            "Invalid classical question",
        )
        options = q["criteria"]
        require(
            isinstance(options, dict)
            and list(options) == list("ABCD")
            and all(isinstance(v, str) and v.strip() for v in options.values())
            and len(set(options.values())) == 4,
            "Invalid classical options",
        )
    require(gold.keys() == question_ids, "Classical question/gold IDs differ")
    require(len(groups) == 24, "Expected 24 excerpt groups")
    for eid, group in groups.items():
        require(set(group) == set(VARIANTS), f"Missing paired task/control: {eid}")
        base = group["a"]
        require(group["p"]["state"] == base["state"], f"Main poem differs: {eid}")
        for s in group.values():
            require(
                s["source"] == base["source"] and s["tags"] == base["tags"],
                f"Paired metadata differs: {eid}",
            )
        for kind in ("c", "n"):
            control = group[kind]
            q, cq = base["questions"][0], control["questions"][0]
            require(
                {k: v for k, v in q.items() if k != "id"}
                == {k: v for k, v in cq.items() if k != "id"},
                f"Control question/options differ: {eid}",
            )
            require(
                gold[q["id"]]["expected"] == gold[cq["id"]]["expected"],
                f"Control gold differs: {eid}",
            )
            require(control["state"] != base["state"], f"Control did not replace poem: {eid}")
        require(group["c"]["state"] != group["n"]["state"], f"Controls identical: {eid}")
        require(
            group["n"]["state"] == {"text": "متن در این آزمون ارائه نشده است."},
            f"No-poem control contains unexpected text: {eid}",
        )
    require(
        Counter(g["a"]["source"]["poet"] for g in groups.values()) == dict.fromkeys(POETS, 6),
        "Poet counts differ",
    )
    for task in ("p", "a"):
        require(
            Counter(gold[g[task]["questions"][0]["id"]]["expected"] for g in groups.values())
            == dict.fromkeys("ABCD", 6),
            "Classical main labels unbalanced",
        )
    banks = defaultdict(list)
    for group in groups.values():
        q = group["a"]["questions"][0]
        banks[tuple(q["criteria"].items())].append(gold[q["id"]]["expected"])
    require(
        len(banks) == 6
        and all(Counter(labels) == dict.fromkeys("ABCD", 1) for labels in banks.values()),
        "Situation banks must each serve four distinct correct answers",
    )
    return gold


def load_classical_dataset(root, manifest):
    require(set(manifest["sha256"]) == FROZEN_FILES, "Invalid classical frozen file list")
    for name, digest in manifest["sha256"].items():
        require(
            hashlib.sha256((root / name).read_bytes()).hexdigest() == digest,
            f"Frozen dataset hash mismatch: {name}; create a documented revision",
        )
    scenarios = read_jsonl(root / "scenarios.jsonl")
    gold = validate_classical_cases(scenarios, read_jsonl(root / "gold.jsonl"))
    main = [s for s in scenarios if s["condition"] == "poem"]
    controls = [s for s in scenarios if s["condition"] != "poem"]
    require(
        manifest["counts"] == {"choice": len(main)} and manifest["excerpts"] == 24,
        "Classical counts differ",
    )
    require(
        manifest["diagnostic_counts"] == dict(Counter(s["condition"] for s in controls)),
        "Diagnostic counts differ",
    )
    require(manifest["repeat_scenarios"] == [], "Classical has no repeat phase")
    by_id = {s["id"]: s for s in main}
    ids = manifest["smoke_scenarios"]
    require(
        isinstance(ids, list)
        and len(ids) == 8
        and len(set(ids)) == 8
        and all(sid in by_id for sid in ids),
        "Invalid classical smoke subset",
    )
    smoke = [by_id[sid] for sid in ids]
    require(
        Counter(s["source"]["poet"] for s in smoke) == dict.fromkeys(POETS, 2)
        and Counter(s["category"] for s in smoke) == {"paraphrase": 4, "application": 4},
        "Smoke must cover both tasks and all poets",
    )
    return Dataset(
        main,
        gold,
        [],
        manifest,
        smoke,
        {s["questions"][0]["id"]: gold[s["questions"][0]["id"]] for s in smoke},
        controls,
    )
