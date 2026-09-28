"""Sequential SDK runner with an append-only, flushed request journal."""

import hashlib
import json
import logging
import math
import os
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from .data import payload

LOG = logging.getLogger(__name__)
SCORING_VERSION = "1.0.1"


def utc_now():
    return datetime.now(UTC).isoformat()


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def plan_jobs(dataset, suite, model):
    jobs = []
    scenarios = dataset.smoke if suite == "smoke" else dataset.scenarios
    gold = dataset.smoke_gold if suite == "smoke" else dataset.gold

    def add(scenario, phase, observation):
        jobs.append(
            {
                "id": f"{phase}-{scenario['id']}-{observation}",
                "phase": phase,
                "observation": observation,
                "scenario": scenario,
                "gold": {q["id"]: gold[q["id"]] for q in scenario["questions"]},
                "request": payload(scenario, model, english=phase == "english"),
            }
        )

    for s in scenarios:
        add(s, "main" if suite == "full" else "smoke", 0)
    if suite == "full":
        for scenario in dataset.diagnostics:
            add(scenario, scenario["condition"], 0)
        for s in scenarios:
            selected = [q for q in s["questions"] if "english" in q]
            if selected:
                add({**s, "questions": selected}, "english", 0)
        for observation in (1, 2):
            for s in scenarios:
                if s["id"] in dataset.manifest["repeat_scenarios"]:
                    add(s, "repeat", observation)
    return jobs


def redact(value):
    """Redact known credentials even if an API error happens to echo one."""
    secret = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        # Keep journals strict JSON; raw_response_text retains the original bytes as text.
        # The scorer rejects these strings as invalid numeric values.
        return str(value)
    return value


def local_api_url(value):
    """Accept a loopback API root without credentials or request-specific components."""
    message = (
        "Local URL must be an HTTP(S) loopback root without credentials, path, query or fragment"
    )
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and parsed.port != 0
            and not any(character.isspace() for character in value)
        )
    except ValueError:
        raise ValueError(message) from None
    if not valid:
        raise ValueError(message)
    return value.rstrip("/")


def error_details(exc, *, local=False):
    status = getattr(exc, "status", None)
    advice = {
        400: "Check request configuration.",
        401: "Check TYPESAFE_API_KEY.",
        403: "Check API key permissions.",
        404: "Check model ID and endpoint.",
        422: "Check request schema and model configuration.",
        429: "Rate limit persisted after bounded SDK retries.",
    }
    if local:
        advice.update(
            {
                401: "--local-url supports unauthenticated servers; check local server settings.",
                403: "Check local server access settings.",
                None: "Check that the local server is running and reachable from this session.",
            }
        )
    return {
        "type": type(exc).__name__,
        "http_status": status,
        "message": advice.get(
            status, "Request failed after SDK handling; inspect error type and raw response."
        ),
        "request_id": getattr(exc, "headers", {}).get("x-typesafe-request-id")
        or getattr(exc, "headers", {}).get("x-request-id"),
    }


def run(dataset, output, suite="full", model="jev-1.13.0", client=None, *, local_url=None):
    from typesafe_sdk import RetryPolicy, TypeSafeClient, TypeSafeError

    if local_url is not None:
        local_url = local_api_url(local_url)
        if client is not None:
            raise ValueError("Pass either client or local_url, not both")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    jobs = plan_jobs(dataset, suite, model)
    meta = {
        "schema_version": 1,
        "scoring_version": SCORING_VERSION,
        "created_at": utc_now(),
        "suite": suite,
        "requested_model": model,
        "sdk_version": version("typesafe-sdk"),
        "dataset_manifest": dataset.manifest,
        "pairs": dataset.pairs if suite == "full" else [],
        "planned_questions": sum(len(j["scenario"]["questions"]) for j in jobs),
        "timeout_seconds": 20.0,
        "max_retries": 2,
        "retry_budget_seconds": 45.0,
        "implementation_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))
        },
        "jobs": jobs,
    }
    if local_url is not None:
        meta["local_url"] = local_url
        LOG.info("Using local API at %s with model %s", local_url, model)
    write_json(output / "run.json", meta)
    owned = client is None
    interrupted, abort, completed = False, None, 0
    try:
        if owned:
            local_options = {}
            if local_url is not None:
                import httpx2

                # The SDK requires a key. Never forward the user's cloud key or proxy local traffic.
                local_options = {
                    "api_key": "local-unused",
                    "base_url": local_url,
                    "http_client": httpx2.Client(timeout=20.0, trust_env=False),
                }
            client = TypeSafeClient(
                model=model,
                timeout=20.0,
                retry=RetryPolicy(max_retries=2, timeout=45.0),
                **local_options,
            )
        with (output / "requests.jsonl").open("x", encoding="utf-8") as stream:

            def append(event):
                stream.write(json.dumps(redact(event), ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

            for index, job in enumerate(jobs, 1):
                LOG.info(
                    "Request %d/%d: %s (%d questions)",
                    index,
                    len(jobs),
                    job["id"],
                    len(job["scenario"]["questions"]),
                )
                started = time.perf_counter()
                append({"event": "started", "job_id": job["id"], "at": utc_now()})
                event = {"event": "finished", "job_id": job["id"], "at": utc_now()}
                try:
                    response = client.system_one(**job["request"])
                    raw = response.raw_http_response
                    event.update(
                        status="ok",
                        raw_response=raw.json(),
                        raw_response_text=raw.text,
                        request_id=raw.headers.get("x-typesafe-request-id")
                        or raw.headers.get("x-request-id"),
                        actual_request=json.loads(raw.request.content),
                        returned_model=response.model,
                        usage=response.usage.model_dump(),
                    )
                    event["model_mismatch"] = response.model != model
                    if event["actual_request"] != job["request"]:
                        event.update(
                            status="error",
                            error={
                                "type": "PayloadMismatch",
                                "message": "SDK wire payload differs from frozen request.",
                            },
                        )
                    if event["model_mismatch"]:
                        LOG.warning(
                            "Model mismatch in %s: requested %s, returned %s",
                            job["id"],
                            model,
                            response.model,
                        )
                except TypeSafeError as exc:
                    error = error_details(exc, local=local_url is not None)
                    event.update(
                        status="error",
                        error=error,
                        raw_response=getattr(exc, "body", None),
                        request_id=error["request_id"],
                    )
                    LOG.error(
                        "%s: %s (HTTP %s). %s",
                        job["id"],
                        error["type"],
                        error["http_status"],
                        error["message"],
                    )
                    if error["http_status"] in {400, 401, 403, 404, 422}:
                        abort = error
                event["elapsed_seconds"] = time.perf_counter() - started
                event["at"] = utc_now()
                append(event)
                completed += 1
                if abort:
                    break
    except KeyboardInterrupt:
        interrupted = True
        LOG.warning(
            "Interrupted; completed responses are preserved. Rebuild with the report command."
        )
    except TypeSafeError as exc:
        abort = error_details(exc, local=local_url is not None)
        abort["message"] = (
            "Local client configuration failed; check the local server URL."
            if local_url is not None
            else "Client configuration failed; check TYPESAFE_API_KEY and TYPESAFE_BASE_URL."
        )
        LOG.error("%s: %s", abort["type"], abort["message"])
    finally:
        if owned and client is not None:
            client.close()
        write_json(
            output / "completion.json",
            {
                "finished_at": utc_now(),
                "completed_requests": completed,
                "planned_requests": len(jobs),
                "interrupted": interrupted,
                "abort": abort,
                "all_requests_finished": completed == len(jobs),
            },
        )
    return output
