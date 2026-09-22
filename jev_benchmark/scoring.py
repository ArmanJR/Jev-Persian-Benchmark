"""Deterministic local metrics. Invalid answers are failures, never wrong answers."""

import math
from statistics import mean

from .data import THRESHOLDS

# Live responses expose hundredth precision. Allow the independent rounding
# error of each displayed value, without renormalizing the returned values.
WIRE_HALF_UNIT = 0.005


def number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Invalid {label}: expected a finite number in [{low}, {high}]")
    return value


def distribution(raw, keys):
    if not isinstance(raw, dict) or set(raw) != set(keys):
        raise ValueError("Probability keys do not match requested criteria")
    for p in raw.values():
        number(p, 0, 1, "probability")
    if not math.isclose(sum(raw.values()), 1, abs_tol=len(keys) * WIRE_HALF_UNIT + 1e-9):
        raise ValueError("Probabilities do not sum to one")
    return raw


def score_answer(question, expected, answer):
    if not isinstance(answer, dict) or answer.get("type") != question["type"]:
        raise ValueError("Missing answer or incorrect answer type")
    kind = question["type"]
    out = {"primitive": kind, "expected": expected}
    if kind == "noul":
        p = number(answer.get("noul"), 0, 1, "Noul probability")
        predicted = p >= THRESHOLDS["noul"]
        out.update(
            predicted=predicted,
            numeric=p,
            correct=predicted == expected,
            high_confidence=p <= 0.2 or p >= 0.8,
            brier=(p - expected) ** 2,
        )
    else:
        confidence = number(answer.get("confidence"), 0, 1, "confidence")
        out["high_confidence"] = confidence >= THRESHOLDS["high_confidence"]
        if kind == "choice":
            ps = distribution(answer.get("probabilities"), question["criteria"])
            predicted = answer.get("choice")
            if predicted not in question["criteria"] or ps[predicted] < max(ps.values()) - 1e-4:
                raise ValueError("Choice is invalid or is not a maximum-probability option")
            out.update(
                predicted=predicted,
                correct=predicted == expected,
                brier=sum((p - (k == expected)) ** 2 for k, p in ps.items()),
            )
        else:
            levels = [str(i) for i in range(len(question["criteria"]))]
            ps = distribution(answer.get("probabilities"), levels)
            legend = answer.get("legend")
            if legend != dict(zip(levels, question["criteria"], strict=True)):
                raise ValueError("Score legend does not match requested rubric")
            value = number(answer.get("score"), 0, len(levels) - 1, "Score value")
            rounding_budget = WIRE_HALF_UNIT * (1 + sum(range(len(levels))))
            if not math.isclose(
                value, sum(int(k) * p for k, p in ps.items()), abs_tol=rounding_budget + 1e-9
            ):
                raise ValueError("Score does not match probability-weighted rubric position")
            error = abs(value - expected)
            out.update(
                predicted=min(len(levels) - 1, math.floor(value + 0.5)),
                numeric=value,
                correct=error <= THRESHOLDS["score_tolerance"],
                absolute_error=error,
                normalized_error=error / (len(levels) - 1),
            )
    return out


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def summarize(rows):
    """Rows with errors count toward planned coverage, but not accuracy denominators."""
    result = {}
    for kind in ("choice", "noul", "score"):
        group = [r for r in rows if r["primitive"] == kind]
        ok = [r for r in group if r["status"] == "ok"]
        high = [r for r in ok if r["metrics"]["high_confidence"]]
        metrics = [r["metrics"] for r in ok]
        data = {
            "planned": len(group),
            "valid": len(ok),
            "failures": sum(r["status"] == "error" for r in group),
            "not_completed": sum(r["status"] == "not_completed" for r in group),
            "correct": sum(m["correct"] for m in metrics),
            "accuracy" if kind != "score" else "within_half": ratio(
                sum(m["correct"] for m in metrics), len(ok)
            ),
            "high_confidence_n": len(high),
            "high_confidence_coverage": ratio(len(high), len(ok)),
            "high_confidence_accuracy": ratio(
                sum(r["metrics"]["correct"] for r in high), len(high)
            ),
        }
        if kind == "score":
            data.update(
                mae=mean(m["absolute_error"] for m in metrics) if metrics else None,
                normalized_mae=mean(m["normalized_error"] for m in metrics) if metrics else None,
            )
        else:
            data["brier"] = mean(m["brier"] for m in metrics) if metrics else None
        if kind == "noul":
            tp = sum(m["predicted"] and m["expected"] for m in metrics)
            fp = sum(m["predicted"] and not m["expected"] for m in metrics)
            fn = sum(not m["predicted"] and m["expected"] for m in metrics)
            data.update(
                precision=ratio(tp, tp + fp),
                recall=ratio(tp, tp + fn),
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
            )
        result[kind] = data
    return result
