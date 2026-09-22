# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib==3.10.6"]
# ///
"""Regenerate README plots from a completed run; prices are explicit estimates."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, PercentFormatter

AREAS = {
    "intent": "Intent",
    "sentiment": "Sentiment",
    "reading": "Reading",
    "negation": "Negation",
    "idioms": "Idioms",
    "pragmatics": "Pragmatics",
    "scenarios": "Scenario decisions",
    "moderation": "Moderation",
    "semantic": "Semantic matching",
    "extraction": "Extraction",
}
TEAL, AMBER, BLUE = "#087f8c", "#c27315", "#5167a8"


def finish(fig, output, name):
    for extension in ("png", "svg"):
        fig.savefig(output / f"{name}.{extension}", dpi=180, facecolor="white")
    plt.close(fig)


def plot_comparison(summary, output, jev_rate):
    pricing_path = Path(__file__).resolve().parents[1] / "docs/comparison_pricing.json"
    pricing = json.loads(pricing_path.read_text(encoding="utf-8"))
    models = [
        {"label": summary["requested_model"], "input": jev_rate, "output": 0},
        *pricing["models"],
    ]
    usage = summary["usage"]
    inputs = [usage["input_tokens"] * m["input"] / 1_000_000 for m in models]
    outputs = [usage["output_tokens"] * m["output"] / 1_000_000 for m in models]
    totals = [i + o for i, o in zip(inputs, outputs, strict=True)]
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    fig.suptitle("Estimated cost at equal token volumes", fontsize=17, fontweight="bold")
    ax.set_title(
        f"{usage['input_tokens']:,} input + {usage['output_tokens']:,} answer tokens"
        " · similar accuracy assumed · reasoning off",
        fontsize=10,
        loc="left",
        pad=16,
    )
    ax.barh(range(len(models)), inputs, color=TEAL, height=0.55, label="Input")
    ax.barh(range(len(models)), outputs, left=inputs, color=BLUE, height=0.55, label="Output")
    ax.set_yticks(range(len(models)), [m["label"] for m in models])
    ax.invert_yaxis()
    ax.set_xlim(0, max(totals) * 1.44)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5, prune="upper"))
    ax.set_xlabel(f"USD · undiscounted rates checked {pricing['checked_at']} · smoke excluded")
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", alpha=0.16)
    ax.set_axisbelow(True)
    ax.legend(loc="upper right", frameon=False)
    for y, total in enumerate(totals):
        label = f"${total:.6f}"
        if totals[0] > 0:
            label += f" · {total / totals[0]:.1f}× Jev"
        ax.text(total + max(totals) * 0.015, y, label, va="center", fontsize=10)
    finish(fig, output, "cost-comparison")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=Path("results/full-v1"))
    parser.add_argument("--output", type=Path, default=Path("docs/plots"))
    parser.add_argument("--usd-per-million-input", type=float, default=0.042)
    args = parser.parse_args()
    if args.usd_per_million_input < 0:
        parser.error("Input-token price must be nonnegative")
    summary = json.loads((args.run / "summary.json").read_text(encoding="utf-8"))
    meta = json.loads((args.run / "run.json").read_text(encoding="utf-8"))
    if not summary["completion"]["complete"] or summary["suite"] != "full":
        parser.error("Plots require a completed full run")
    args.output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.edgecolor": "#b8c1cc",
            "text.color": "#243341",
            "axes.labelcolor": "#243341",
            "xtick.color": "#52616f",
            "ytick.color": "#243341",
            "svg.hashsalt": "jev-persian-v1",
        }
    )

    fig, (left, right) = plt.subplots(
        1, 2, figsize=(11, 5.4), layout="constrained", gridspec_kw={"width_ratios": [1, 1.35]}
    )
    fig.suptitle(
        f"{summary['requested_model']} · Persian benchmark", fontsize=17, fontweight="bold"
    )
    kinds = ["choice", "noul", "score"]
    metrics = [summary["main"][kind] for kind in kinds]
    values = [m.get("accuracy", m.get("within_half")) * 100 for m in metrics]
    left.barh(range(3), values, color=[TEAL, TEAL, AMBER], height=0.52)
    left.set_yticks(range(3), ["Choice", "Noul", "Score"])
    left.invert_yaxis()
    left.set_xlim(0, 100)
    left.xaxis.set_major_formatter(PercentFormatter())
    left.set_xlabel("Accuracy; Score uses ±0.5-level tolerance")
    left.set_title("Main results · 480 questions", loc="left", pad=18)
    left.grid(axis="x", alpha=0.16)
    left.set_axisbelow(True)
    left.tick_params(axis="y", length=0)
    for y, (m, value) in enumerate(zip(metrics, values, strict=True)):
        left.text(
            3,
            y,
            f"{value:.1f}%  ·  {m['correct']}/{m['valid']}",
            va="center",
            color="white",
            fontweight="bold",
            fontsize=12,
        )

    errors = [summary["categories"][area]["score"]["mae"] for area in AREAS]
    right.barh(
        range(10),
        errors,
        color=[AMBER if area in {"negation", "scenarios"} else TEAL for area in AREAS],
        height=0.64,
    )
    right.set_yticks(range(10), AREAS.values())
    right.invert_yaxis()
    right.set_xlim(0, max(errors) * 1.27)
    right.xaxis.set_major_locator(MaxNLocator(nbins=4, prune="upper"))
    right.set_xlabel("Mean absolute error in levels · lower is better")
    right.set_title("Score error by area · n=8 each", loc="left", pad=18)
    right.grid(axis="x", alpha=0.16)
    right.set_axisbelow(True)
    right.tick_params(axis="y", length=0)
    for y, value in enumerate(errors):
        right.text(value + 0.005, y, f"{value:.3f}", va="center", fontsize=9)
    finish(fig, args.output, "performance")

    jobs = {j["id"]: j for j in meta["jobs"]}
    usage = defaultdict(int)
    for line in (args.run / "requests.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["event"] == "finished":
            usage[jobs[event["job_id"]]["phase"]] += event["usage"]["input_tokens"]
    total_usd = sum(usage.values()) * args.usd_per_million_input / 1_000_000
    if sum(usage.values()) != summary["usage"]["input_tokens"]:
        raise ValueError("Journal and summary token totals differ")
    phases = ["main", "english", "repeat"]
    cents = [usage[p] * args.usd_per_million_input / 10_000 for p in phases]
    fig, ax = plt.subplots(figsize=(10, 3.6), layout="constrained")
    fig.suptitle(f"Estimated API cost · ${total_usd:.6f} total", fontsize=17, fontweight="bold")
    ax.set_title(
        f"${args.usd_per_million_input:g} / million input tokens · output free · smoke excluded",
        fontsize=10,
        loc="left",
        pad=14,
    )
    ax.barh(range(3), cents, color=[TEAL, BLUE, AMBER], height=0.52)
    ax.set_yticks(
        range(3), ["Main · 480 evaluations", "English · 48 evaluations", "Repeats · 96 evaluations"]
    )
    ax.invert_yaxis()
    ax.set_xlim(0, max(cents) * 1.38 if max(cents) else 1)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=4, prune="upper"))
    ax.set_xlabel("US cents (100 cents = $1)")
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", alpha=0.16)
    ax.set_axisbelow(True)
    for y, (phase, value) in enumerate(zip(phases, cents, strict=True)):
        ax.text(
            value + max(cents) * 0.02,
            y,
            f"{value:.3f}¢ · {usage[phase]:,} tokens",
            va="center",
            fontsize=10,
        )
    finish(fig, args.output, "cost")
    plot_comparison(summary, args.output, args.usd_per_million_input)
    print(f"Saved performance, cost, and comparison plots to {args.output}")


if __name__ == "__main__":
    main()
