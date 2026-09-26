# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Freeze the authored classical-transfer pilot; normal preparation is offline."""

import argparse
import hashlib
import html
import json
import logging
import random
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1] / "data" / "classical"
PARAPHRASE = "کدام عبارت، معنای اصلی متن داده‌شده را بهتر بیان می‌کند؟"
APPLICATION = "کدام موقعیت، پیام اصلی متن داده‌شده را بهتر نشان می‌دهد؟"
NO_POEM = "متن در این آزمون ارائه نشده است."


def require(condition, message):
    if not condition:
        raise ValueError(message)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def parse_verses(markup):
    """Only verse columns, never Ganjoor's AI glosses or reader comments."""
    columns = re.findall(r'<div class="m[12]">\s*<p>(.*?)</p>\s*</div>', markup, re.S)
    return [html.unescape(re.sub(r"<[^>]+>", "", text)).strip() for text in columns]


def fetch_sources(root):
    path = root / "sources.json"
    require(not path.exists(), "Source snapshot already exists; do not overwrite frozen evidence")
    authored = json.loads((root / "authored.json").read_text())

    def fetch(url):
        require(url.startswith("https://ganjoor.net/"), "Unexpected source host")
        with urlopen(url, timeout=30) as response:
            raw = response.read()
        markup = raw.decode("utf-8")
        lines = parse_verses(markup)
        require(lines and len(lines) % 2 == 0, f"Missing/incomplete verse columns: {url}")
        LOG.info("Retrieved %d hemistichs: %s", len(lines), url)
        return url, {
            "title": html.unescape(re.search(r"<title>(.*?)</title>", markup, re.S)[1]),
            "retrieved_at": datetime.now(UTC).isoformat(),
            "html_sha256": hashlib.sha256(raw).hexdigest(),
            "lines": lines,
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        sources = dict(pool.map(fetch, authored["sources"]))
    path.write_bytes(json_bytes(sources))


def compile_dataset(authored, sources):
    entries = authored["excerpts"]
    require(len(entries) == 24, "Pilot requires 24 excerpts")
    require(
        Counter(e["poet"] for e in entries)
        == dict.fromkeys(("saadi", "hafez", "rumi", "ferdowsi"), 6),
        "Pilot requires six excerpts per poet",
    )
    require(set(sources) == set(authored["sources"]), "Source snapshot/list mismatch")
    scenarios, gold, ids, quotes = [], [], set(), set()
    labels = list(range(4)) * 6
    random.Random(917).shuffle(labels)
    banks = authored["situation_banks"]
    require(
        len(banks) == 6 and all(len(bank) == 4 for bank in banks.values()),
        "Expected six four-situation banks",
    )
    members = [item["excerpt_id"] for bank in banks.values() for item in bank]
    require(
        Counter(members) == Counter(e["id"] for e in entries),
        "Each excerpt must own exactly one situation",
    )
    for index, entry in enumerate(entries):
        eid = entry["id"]
        require(eid == f"c{index + 1:03d}" and eid not in ids, "Invalid excerpt ID/order")
        ids.add(eid)
        start, count = entry["start"], entry["lines"]
        require(
            type(start) is int
            and start >= 0
            and start % 2 == 0
            and type(count) is int
            and count > 0
            and count % 2 == 0,
            f"Invalid verse selection: {eid}",
        )
        source = sources[entry["url"]]
        selected = source["lines"][start : start + count]
        require(len(selected) == count, f"Verse range exceeds source: {eid}")
        poem = "\n".join(selected)
        require(poem not in quotes, f"Duplicate excerpt: {eid}")
        quotes.add(poem)
        require(poem == entry["verified_text"], f"Reviewed quotation differs from source: {eid}")
        for field in ("modern_prose", "theme", "review_note"):
            require(
                isinstance(entry[field], str) and entry[field].strip(), f"Missing {field}: {eid}"
            )
        metadata = {
            "excerpt_id": eid,
            "poet": entry["poet"],
            "url": entry["url"],
            "title": source["title"],
            "first_hemistich": start + 1,
        }
        for task in ("paraphrase", "application"):
            authored_q = entry[task]
            if task == "paraphrase":
                options = authored_q["options"]
                position = labels[index]
                distractors = options[1:]
                random.Random(f"{eid}/{task}/v1").shuffle(distractors)
                ordered = distractors[:position] + [options[0]] + distractors[position:]
            else:
                bank_name = authored_q["bank"]
                bank = list(banks[bank_name])
                random.Random(f"{bank_name}/v1").shuffle(bank)
                require(eid in [item["excerpt_id"] for item in bank], f"Wrong bank: {eid}")
                position = next(i for i, item in enumerate(bank) if item["excerpt_id"] == eid)
                options = ordered = [item["text"] for item in bank]
            require(
                isinstance(options, list)
                and len(options) == 4
                and all(isinstance(v, str) and v.strip() for v in options)
                and len(set(options)) == 4,
                f"Invalid options: {eid}/{task}",
            )
            require(
                isinstance(authored_q["rationale"], str) and authored_q["rationale"].strip(),
                f"Missing rationale: {eid}/{task}",
            )
            criteria = dict(zip("ABCD", ordered, strict=True))
            variants = [("poem", poem, "p" if task == "paraphrase" else "a")]
            if task == "application":
                variants += [
                    ("prose_control", entry["modern_prose"], "c"),
                    ("no_poem_control", NO_POEM, "n"),
                ]
            for condition, state, suffix in variants:
                sid = eid + suffix
                qid = sid + "q1"
                scenarios.append(
                    {
                        "id": sid,
                        "category": task,
                        "condition": condition,
                        "tags": [entry["poet"], entry["theme"]],
                        "source": metadata,
                        "state": {"text": state},
                        "questions": [
                            {
                                "id": qid,
                                "type": "choice",
                                "instructions": PARAPHRASE if task == "paraphrase" else APPLICATION,
                                "criteria": criteria,
                            }
                        ],
                    }
                )
                gold.append(
                    {"id": qid, "expected": "ABCD"[position], "rationale": authored_q["rationale"]}
                )
    return scenarios, gold


def prepare(root, check=False):
    authored_bytes = (root / "authored.json").read_bytes()
    source_bytes = (root / "sources.json").read_bytes()
    authored, sources = json.loads(authored_bytes), json.loads(source_bytes)
    scenarios, gold = compile_dataset(authored, sources)
    outputs = {
        "scenarios.jsonl": b"".join(
            (json.dumps(s, ensure_ascii=False) + "\n").encode() for s in scenarios
        ),
        "gold.jsonl": b"".join((json.dumps(g, ensure_ascii=False) + "\n").encode() for g in gold),
        "authored.json": authored_bytes,
        "sources.json": source_bytes,
    }
    manifest = {
        "benchmark": "classical_transfer",
        "revision": authored["revision"],
        "counts": {"choice": 48},
        "excerpts": 24,
        "diagnostic_counts": {"prose_control": 24, "no_poem_control": 24},
        "thresholds": {"noul": 0.5, "high_confidence": 0.8, "score_tolerance": 0.5},
        "repeat_scenarios": [],
        "smoke_scenarios": [f"c{i:03d}{task}" for i in (1, 7, 13, 19) for task in ("p", "a")],
        "annotation": authored["annotation"],
        "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()},
    }
    outputs["manifest.json"] = json_bytes(manifest)
    old = root / "manifest.json"
    if old.exists():
        previous = json.loads(old.read_bytes())
        require(
            previous["revision"] != manifest["revision"] or previous == manifest,
            "Frozen revision changed; document changes and bump the authored revision",
        )
    for name, data in outputs.items():
        path = root / name
        if check:
            require(path.exists() and path.read_bytes() == data, f"Reproduction differs: {name}")
        else:
            path.write_bytes(data)
    LOG.info("%s 24 excerpts, 48 main questions, 48 controls", "Verified" if check else "Prepared")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--fetch-sources", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.fetch_sources:
        fetch_sources(args.output)
    else:
        prepare(args.output, args.check)


if __name__ == "__main__":
    main()
