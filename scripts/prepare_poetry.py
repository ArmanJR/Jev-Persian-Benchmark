# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Rebuild the poetry dataset from byte-preserved sources and a reviewed edit list."""

import argparse
import copy
import hashlib
import json
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1] / "data" / "poetry"
SOURCE_FILES = {
    "questions-outliers.json": "data/gherabat-book/questions-outliers.json",
    "answer_keys.json": "data/gherabat-book/answer_keys.json",
    "legacy-41.json": "preprocess-data/benchmark_dataset.json",
}
INSTRUCTIONS = "با توجه به صورت سؤال، گزینهٔ درست را بر پایهٔ معنا و پیام متن‌ها انتخاب کن."


def require(condition, message):
    if not condition:
        raise ValueError(message)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def jsonl_bytes(rows):
    return "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in rows).encode()


def comparison_text(text):
    """Comparison only: never replace the original Persian spelling with this value."""
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans("يك", "یک"))
    return re.sub(r"[\W_]+", "", text)


def compile_dataset(source, answer_keys, legacy, review):
    questions, pages = {}, {}
    for page in source["pages"]:
        require(type(page["page_number"]) is int and page["page_number"] > 0, "Invalid page")
        for original in page["data"]["questions"]:
            q = copy.deepcopy(original)
            qid = q["id"]
            require(type(qid) is int and qid > 0 and qid not in questions, "Duplicate/invalid ID")
            require(isinstance(q["stem"], str) and q["stem"].strip(), f"Empty stem: {qid}")
            require(
                len(q["options"]) == 4
                and all(type(o["label"]) is int for o in q["options"])
                and sorted(o["label"] for o in q["options"]) == [1, 2, 3, 4],
                f"Invalid option labels: {qid}",
            )
            q["options"].sort(key=lambda o: o["label"])
            for option in q["options"]:
                require(
                    all(isinstance(option[k], str) for k in ("mesra1", "mesra2"))
                    and (option["mesra1"].strip() or option["mesra2"].strip()),
                    f"Empty/invalid option: {qid}/{option['label']}",
                )
            require(
                type(answer_keys.get(str(qid))) is int and 1 <= answer_keys[str(qid)] <= 4,
                f"Missing/invalid answer key: {qid}",
            )
            questions[qid], pages[qid] = q, page["page_number"]

    excluded = {int(k) for k in review["excluded"]}
    require(excluded <= questions.keys(), "Exclusion refers to an unknown question")
    require(all(review["excluded"].values()), "Every exclusion needs a reason")
    retained = questions.keys() - excluded
    legacy_by_id = {q["id"]: q for q in legacy}
    changed, swaps, stripped = set(), 0, 0
    for key, labels in review["reverse_options"].items():
        qid = int(key)
        require(qid in retained and qid in legacy_by_id, f"Invalid order repair: {qid}")
        require(len(labels) == len(set(labels)) and set(labels) <= {1, 2, 3, 4}, "Invalid swaps")
        for label in labels:
            option = questions[qid]["options"][label - 1]
            reference = legacy_by_id[qid]["options"][label - 1].split(" - ")
            require(len(reference) == 2, f"Invalid order reference: {qid}/{label}")
            a, b = map(comparison_text, reference)
            x, y = (comparison_text(option[k]) for k in ("mesra1", "mesra2"))
            require((a == y or b == x) and not (a == x or b == y), "Order evidence differs")
            option["mesra1"], option["mesra2"] = option["mesra2"], option["mesra1"]
            swaps += 1
        changed.add(qid)

    for qid in review["strip_option_labels"]:
        require(qid in retained, f"Invalid label cleanup: {qid}")
        count = 0
        for option in questions[qid]["options"]:
            for field in ("mesra1", "mesra2"):
                before = option[field]
                after = re.sub(r"^\s*(?:[1-4]\s*)?\)\s*", "", before)
                if qid in {93, 94}:
                    after = re.sub(rf"\s*{option['label']}$", "", after)
                if after != before:
                    option[field] = after
                    count += 1
        require(count > 0, f"No labels to remove: {qid}")
        stripped += count
        changed.add(qid)

    for repair in review["replacements"]:
        qid, label, field = repair["question_id"], repair["option"], repair["field"]
        require(qid in retained, f"Invalid replacement: {qid}")
        require(repair["reason"] and repair["reference"], "Replacement needs evidence")
        require(
            (label is None and field == "stem")
            or (type(label) is int and label in {1, 2, 3, 4} and field in {"mesra1", "mesra2"}),
            "Invalid replacement target",
        )
        target = questions[qid] if label is None else questions[qid]["options"][label - 1]
        require(target[field] == repair["before"], f"Replacement precondition differs: {qid}")
        target[field] = repair["after"]
        changed.add(qid)

    scenarios, gold = [], []
    for qid in sorted(retained):
        q = questions[qid]
        options = [
            "\n".join(o[k].strip() for k in ("mesra1", "mesra2") if o[k].strip())
            for o in q["options"]
        ]
        signatures = [tuple(sorted(comparison_text(s) for s in o.splitlines())) for o in options]
        require(len(set(signatures)) == 4, f"Duplicate options: {qid}")
        require(not any("تضمین بیت را اینجا وارد کنید" in o for o in options), "Placeholder option")
        sid = f"p{qid:04d}"
        question_id = sid + "q1"
        scenarios.append(
            {
                "id": sid,
                "category": "literary_semantics",
                "tags": ["persian_literature"],
                "source": {"question_id": qid, "page": pages[qid]},
                "state": {"text": q["stem"]},
                "questions": [
                    {
                        "id": question_id,
                        "type": "choice",
                        "instructions": INSTRUCTIONS,
                        "criteria": dict(zip("ABCD", options, strict=True)),
                    }
                ],
            }
        )
        gold.append({"id": question_id, "expected": "ABCD"[answer_keys[str(qid)] - 1]})

    smoke_ids = set()
    for label in "ABCD":
        group = [s for s, g in zip(scenarios, gold, strict=True) if g["expected"] == label]
        require(len(group) >= 3, f"Insufficient questions for smoke label {label}")
        smoke_ids.update(group[i]["id"] for i in (0, len(group) // 2, len(group) - 1))
    stats = {
        "source_questions": len(questions),
        "source_answer_keys": len(answer_keys),
        "unused_answer_keys": len(set(answer_keys) - {str(qid) for qid in questions}),
        "excluded_questions": len(excluded),
        "retained_questions": len(scenarios),
        "repaired_questions": len(changed),
        "reordered_options": swaps,
        "cleaned_option_fields": stripped,
        "text_replacements": len(review["replacements"]),
    }
    return scenarios, gold, sorted(smoke_ids), stats


def prepare(root=ROOT, source_root=None, *, check=False):
    root = Path(root)
    review_bytes = (root / "review.json").read_bytes()
    review = json.loads(review_bytes)
    source_bytes = {}
    for name, relative in SOURCE_FILES.items():
        origin = Path(source_root) / relative if source_root is not None else root / "source" / name
        raw = origin.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == review["source_sha256"][name],
            f"Source hash mismatch: {name}",
        )
        source_bytes[name] = raw
    scenarios, gold, smoke_ids, stats = compile_dataset(
        *(json.loads(source_bytes[name]) for name in SOURCE_FILES), review
    )
    files = {f"source/{name}": raw for name, raw in source_bytes.items()}
    files.update({"scenarios.jsonl": jsonl_bytes(scenarios), "gold.jsonl": jsonl_bytes(gold)})
    manifest = {
        "benchmark": "poetry",
        "revision": review["revision"],
        "review": (
            "Recorded extraction review; see REVIEW.md and review.json. "
            "Keys are not independently reannotated."
        ),
        "provenance": {
            k: review[k]
            for k in ("source_repository", "source_git_revision", "source_note", "reviewed_at")
        },
        "source_pdf": json.loads(source_bytes["questions-outliers.json"])["source_pdf"],
        "counts": {"choice": len(gold)},
        "label_counts": dict(sorted(Counter(g["expected"] for g in gold).items())),
        "preparation": stats,
        "smoke_scenarios": smoke_ids,
        "repeat_scenarios": [],
        "thresholds": {"noul": 0.5, "high_confidence": 0.8, "score_tolerance": 0.5},
        "sha256": {
            name: hashlib.sha256(raw).hexdigest()
            for name, raw in sorted((files | {"review.json": review_bytes}).items())
        },
    }
    files["manifest.json"] = json_bytes(manifest)
    if check:
        for name, raw in files.items():
            require((root / name).read_bytes() == raw, f"Generated file differs: {name}")
    else:
        existing = root / "manifest.json"
        if (
            existing.exists()
            and json.loads(existing.read_bytes())["revision"] == review["revision"]
        ):
            require(
                existing.read_bytes() == files["manifest.json"],
                "Frozen revision changed; document and bump review.json revision "
                "before regenerating",
            )
        for name, raw in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != raw:
                target.write_bytes(raw)
    LOG.info(
        "%s poetry revision %s: %d retained, %d excluded, %d smoke",
        "Verified" if check else "Prepared",
        review["revision"],
        len(gold),
        stats["excluded_questions"],
        len(smoke_ids),
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, help="Original poetry repository (initial import only)"
    )
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument(
        "--check", action="store_true", help="Verify byte-for-byte reproduction without writing"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        prepare(args.output, args.source, check=args.check)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOG.error("%s: %s", type(exc).__name__, exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
