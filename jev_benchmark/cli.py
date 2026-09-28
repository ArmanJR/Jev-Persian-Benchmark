"""Three small commands: validate, run, and report."""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from .data import load_dataset
from .report import build_report
from .runner import plan_jobs, run


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="General Persian and literary benchmarks for Jev and local compatible models"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate all frozen datasets and diagnostics")
    validate.add_argument("--data", type=Path, default=Path("data"))
    execute = commands.add_parser("run", help="Run the selected dataset's smoke or full evaluation")
    execute.add_argument("--data", type=Path, default=Path("data"))
    execute.add_argument("--suite", choices=["smoke", "full"], default="smoke")
    execute.add_argument("--model", help="Model ID (default: jev-1.13.0 for hosted runs)")
    execute.add_argument(
        "--local-url",
        help="Unauthenticated loopback API root, e.g. http://127.0.0.1:8765; requires --model",
    )
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
            full_jobs = plan_jobs(data, "full", "validation")
            phases = {}
            for job in full_jobs:
                phases[job["phase"]] = phases.get(job["phase"], 0) + len(
                    job["scenario"]["questions"]
                )
            smoke_kind = (
                "subset"
                if data.manifest.get("benchmark") in {"poetry", "classical_transfer"}
                else "separate"
            )
            print(
                f"Valid {data.manifest.get('benchmark', 'general')} revision "
                f"{data.manifest['revision']}: "
                + ", ".join(f"{n} {phase} questions" for phase, n in phases.items())
                + f"; {len(data.smoke_gold)} smoke questions ({smoke_kind}); "
                + f"{len(full_jobs)} full requests."
            )
            return 0
        if args.command == "run":
            if args.local_url is not None and args.model is None:
                raise ValueError("--local-url requires --model with the server's exact model ID")
            model = args.model if args.model is not None else "jev-1.13.0"
            data = load_dataset(args.data)
            if not model.strip():
                raise ValueError("Model ID must not be empty")
            output = args.output or Path("results") / (
                datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + args.suite
            )
            run(data, output, args.suite, model, local_url=args.local_url)
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
