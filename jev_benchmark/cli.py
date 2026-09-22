"""Three small commands: validate, run, and report."""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from .data import load_dataset
from .report import build_report
from .runner import run


def main(argv=None):
    parser = argparse.ArgumentParser(description="Authored Persian benchmark for Jev")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate all frozen datasets and diagnostics")
    validate.add_argument("--data", type=Path, default=Path("data"))
    execute = commands.add_parser("run", help="Run smoke (12) or full evaluation (624 questions)")
    execute.add_argument("--data", type=Path, default=Path("data"))
    execute.add_argument("--suite", choices=["smoke", "full"], default="smoke")
    execute.add_argument("--model", default="jev-1.13.0")
    execute.add_argument("--output", type=Path)
    report = commands.add_parser("report", help="Rebuild a report offline from a saved run")
    report.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Third-party request bodies and configuration must not reach console logs.
    logging.getLogger("typesafe_sdk").setLevel(logging.CRITICAL)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    try:
        if args.command == "validate":
            data = load_dataset(args.data)
            print(
                f"Valid revision {data.manifest['revision']}: 480 main questions, 48 English "
                f"counterparts, "
                "48 repeat questions ×2, 12 separate smoke questions."
            )
            return 0
        if args.command == "run":
            data = load_dataset(args.data)
            if not args.model.strip():
                raise ValueError("Model ID must not be empty")
            output = args.output or Path("results") / (
                datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + args.suite
            )
            run(data, output, args.suite, args.model)
        else:
            output = args.directory
        summary = build_report(output)
        c = summary["completion"]
        print(
            f"{c['valid_answers']}/{c['planned_questions']} valid; {c['failed_answers']} failures; "
            f"{c['not_completed']} unfinished. Report: {output / 'report.md'}"
        )
        return 0 if c["complete"] else 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # Paths/schema details are useful; never print arbitrary SDK errors or environment values.
        from .runner import redact

        logging.error("%s: %s", type(exc).__name__, redact(str(exc)))
        return 2


if __name__ == "__main__":
    sys.exit(main())
