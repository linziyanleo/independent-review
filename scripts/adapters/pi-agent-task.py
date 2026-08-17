#!/usr/bin/env python3
"""Run one Pi Agent SDK task with strict validation and a metadata-only receipt."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, NoReturn
import uuid


EXIT_SEMANTIC_FAILURE = 1
EXIT_USAGE = 64
EXIT_INVALID_OUTPUT = 65
EXIT_MODEL_UNAVAILABLE = 69
EXIT_SPAWN_FAILURE = 70
EXIT_CAPTURE_LIMIT = 74
EXIT_TIMEOUT = 75
EXIT_PERMISSION_DENIED = 77
DEFAULT_MAX_INPUT_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_CAPTURE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_RESULT_BYTES = 4 * 1024 * 1024
DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS = 300
ERROR_TEXT_LIMIT = 4096
READ_ONLY_TOOLS = {"read", "grep", "find", "ls"}
THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
DEEP_THINKING_LEVELS = {"xhigh", "max"}
EXPECTED_DOCTOR_RESULT = "PI_AGENT_DOCTOR_OK"
AUTH_PATTERN = re.compile(
    r"(?:use /login|not logged in|no models available|api key|authentication|unauthorized|\b401\b)",
    re.IGNORECASE,
)
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
DEFAULT_RECEIPT_DIR = Path.home() / ".pi" / "agent" / "task-receipts"
_ACTIVE_RECEIPT: "ReceiptWriter | None" = None


@dataclass(frozen=True)
class TimeoutPolicy:
    profile: str
    wall_timeout_seconds: int
    provider_timeout_seconds: int
    stream_idle_timeout_seconds: int
    minimum_wall_timeout_seconds: int
    short_timeout_override: bool

    def diagnostic(self) -> dict[str, Any]:
        return asdict(self)


class TimeoutPolicyError(ValueError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ReceiptWriter:
    """Atomically persist allowlisted task metadata without prompts or model text."""

    def __init__(self, directory: Path, initial: dict[str, Any]) -> None:
        self.directory = directory.expanduser().resolve()
        self.data = {"schema_version": 1, **initial}
        self.path = self.directory / f"{self.data['invocation_id']}.json"
        self._prepare_directory()
        self.write()

    def _prepare_directory(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        mode = self.directory.stat().st_mode & 0o777
        if mode & 0o077:
            raise PermissionError(
                f"receipt directory must not be accessible by group or others: {self.directory}"
            )

    def write(self) -> None:
        self.data["updated_at"] = utc_now()
        encoded = (json.dumps(self.data, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        temporary = self.directory / f".{self.path.name}.{uuid.uuid4()}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def finalize(self, *, outcome: str, kind: str | None = None, **details: Any) -> None:
        self.data["outcome"] = outcome
        if kind is not None:
            self.data["kind"] = kind
        for field in (
            "pi_task_invocations",
            "timeout_scope",
            "timeout_policy",
            "progress_event_count",
            "last_progress",
            "bridge_exit_code",
            "provider",
            "model",
            "thinking_level",
            "provider_request_count",
            "retry_events",
            "agent_start_events",
            "agent_end_events",
            "stop_reason",
            "result_bytes",
            "result_sha256",
        ):
            if details.get(field) is not None:
                self.data[field] = details[field]
        self.data["finished_at"] = utc_now()
        self.write()

    def trace(self) -> dict[str, str]:
        return {
            "invocation_id": str(self.data["invocation_id"]),
            "pi_session_id": str(self.data["pi_session_id"]),
            "receipt_path": str(self.path),
        }


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or a positive integer")
    return number


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def bounded_text(value: str, limit: int = ERROR_TEXT_LIMIT) -> dict[str, Any]:
    if len(value) <= limit:
        return {"text": value, "truncated": False}
    encoded = value.encode("utf-8")
    return {
        "text": value[:limit],
        "truncated": True,
        "characters": len(value),
        "bytes": len(encoded),
        "sha256": sha256_bytes(encoded),
    }


def bounded_json(value: Any, limit: int = ERROR_TEXT_LIMIT) -> Any:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return {"unserializable": True, "type": type(value).__name__}
    if len(rendered) <= limit:
        return value
    return {
        "truncated": True,
        "characters": len(rendered),
        "sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    }


def timeout_profile(mode: str, tools: list[str]) -> dict[str, int | str]:
    if mode == "doctor":
        return {
            "name": "doctor",
            "default_wall": 180,
            "minimum_wall": 60,
            "deep_minimum_wall": 60,
            "default_provider": 120,
        }
    if tools:
        return {
            "name": "tool-loop",
            "default_wall": 2400,
            "minimum_wall": 1200,
            "deep_minimum_wall": 2400,
            "default_provider": 300,
        }
    return {
        "name": "single-turn",
        "default_wall": 1200,
        "minimum_wall": 600,
        "deep_minimum_wall": 1200,
        "default_provider": 300,
    }


def build_timeout_policy(
    *,
    mode: str,
    tools: list[str],
    effort: str | None,
    wall_timeout_seconds: int | None,
    provider_timeout_seconds: int | None,
    stream_idle_timeout_seconds: int,
    allow_short_timeout: bool,
) -> TimeoutPolicy:
    profile = timeout_profile(mode, tools)
    minimum_wall = int(
        profile["deep_minimum_wall"]
        if effort in DEEP_THINKING_LEVELS
        else profile["minimum_wall"]
    )
    effective_wall = wall_timeout_seconds or int(profile["default_wall"])
    if effective_wall < minimum_wall and not allow_short_timeout:
        raise TimeoutPolicyError(
            "wall timeout is below the safe minimum for this task profile",
            profile=profile["name"],
            requested_wall_timeout_seconds=effective_wall,
            minimum_wall_timeout_seconds=minimum_wall,
            effort=effort,
            hint=(
                "omit --timeout-seconds to use the profile default, increase it to the "
                "minimum, or pass --allow-short-timeout only for an intentional bounded probe"
            ),
        )
    provider_ceiling = max(1, effective_wall - 30)
    effective_provider = provider_timeout_seconds or min(
        int(profile["default_provider"]), provider_ceiling
    )
    if effective_provider > provider_ceiling:
        raise TimeoutPolicyError(
            "provider timeout must leave the controller finalization reserve",
            requested_provider_timeout_seconds=effective_provider,
            maximum_provider_timeout_seconds=provider_ceiling,
            wall_timeout_seconds=effective_wall,
        )
    return TimeoutPolicy(
        profile=str(profile["name"]),
        wall_timeout_seconds=effective_wall,
        provider_timeout_seconds=effective_provider,
        stream_idle_timeout_seconds=stream_idle_timeout_seconds,
        minimum_wall_timeout_seconds=minimum_wall,
        short_timeout_override=effective_wall < minimum_wall,
    )


def fail(kind: str, exit_code: int, **details: Any) -> NoReturn:
    outcome = details.pop("outcome", "unknown")
    invocations = details.pop(
        "backend_task_invocations", details.pop("pi_task_invocations", 0)
    )
    receipt_error: dict[str, Any] | None = None
    trace: dict[str, str] = {}
    if _ACTIVE_RECEIPT is not None:
        trace = _ACTIVE_RECEIPT.trace()
        try:
            _ACTIVE_RECEIPT.finalize(
                outcome=outcome, kind=kind, pi_task_invocations=invocations, **details
            )
        except OSError as exc:
            receipt_error = bounded_text(str(exc))
    payload = {
        "type": "independent_review_adapter_diagnostic",
        "kind": kind,
        "outcome": outcome,
        "backend_task_invocations": invocations,
        "details": {"original_request_retried": False, **trace, **details},
    }
    if receipt_error is not None:
        payload["details"]["receipt_persistence_error"] = receipt_error
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    raise SystemExit(exit_code)


class DiagnosticParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        fail("invalid_arguments", EXIT_USAGE, outcome="not_started", error=bounded_text(message))


def build_parser() -> argparse.ArgumentParser:
    parser = DiagnosticParser(
        description=(
            "Run one Pi Agent SDK task in the current process environment, "
            "capture a strict bridge envelope, and persist a metadata-only trace receipt."
        )
    )
    parser.add_argument("mode", choices=("doctor", "prompt"))
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--prompt-file")
    parser.add_argument("--tools")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument(
        "--effort",
        "--thinking",
        dest="effort",
        choices=THINKING_LEVELS,
        help="reasoning effort; defaults to Pi's configured/default thinking level",
    )
    parser.add_argument("--package-dir")
    parser.add_argument(
        "--receipt-dir",
        default=os.environ.get("PI_AGENT_RECEIPT_DIR", str(DEFAULT_RECEIPT_DIR)),
        help="private directory for metadata-only receipts",
    )
    parser.add_argument(
        "--output-format",
        choices=("json", "text"),
        default="json",
        help="json returns result plus trace identifiers; text is compatibility mode",
    )
    parser.add_argument(
        "--timeout-seconds",
        "--wall-timeout-seconds",
        dest="wall_timeout_seconds",
        type=positive_int,
        help="whole-task wall-clock timeout; defaults by mode and tool profile",
    )
    parser.add_argument(
        "--provider-timeout-seconds",
        type=positive_int,
        help="per-provider-request connect/response-header timeout",
    )
    parser.add_argument(
        "--stream-idle-timeout-seconds",
        type=nonnegative_int,
        default=DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS,
        help="HTTP response-body idle timeout; 0 disables only the idle timeout",
    )
    parser.add_argument(
        "--allow-short-timeout",
        action="store_true",
        help="allow a wall timeout below the safe profile minimum for an intentional probe",
    )
    parser.add_argument(
        "--max-input-bytes", type=positive_int, default=DEFAULT_MAX_INPUT_BYTES
    )
    parser.add_argument(
        "--max-capture-bytes", type=positive_int, default=DEFAULT_MAX_CAPTURE_BYTES
    )
    parser.add_argument(
        "--max-result-bytes", type=positive_int, default=DEFAULT_MAX_RESULT_BYTES
    )
    return parser


def read_utf8_file(parser: argparse.ArgumentParser, value: str, label: str) -> str:
    path = Path(value)
    try:
        data = path.read_bytes()
    except OSError as exc:
        parser.error(f"{label} is not readable: {path}: {exc}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        parser.error(f"{label} is not valid UTF-8: {path}: {exc}")
    if not text.strip():
        parser.error(f"{label} is empty: {path}")
    return text


def build_prompt(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    if args.mode == "doctor":
        if any((args.prompt_file, args.tools)):
            parser.error("doctor mode does not accept task content or tools")
        return f"Return exactly this text and nothing else: {EXPECTED_DOCTOR_RESULT}"

    if not args.prompt_file:
        parser.error("prompt mode requires --prompt-file")
    return read_utf8_file(parser, args.prompt_file, "prompt file")


def normalize_tools(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[str]:
    if args.mode == "doctor":
        if args.tools:
            parser.error(f"{args.mode} mode does not accept tools")
        return []
    if args.tools is None:
        return []
    tools = {item for item in re.split(r"[\s,]+", args.tools.strip()) if item}
    unsupported = sorted(tools - READ_ONLY_TOOLS)
    if unsupported:
        parser.error("unsupported non-read-only tools: " + ", ".join(unsupported))
    return sorted(tools)


def locate_package_dir(
    parser: argparse.ArgumentParser, pi_bin: str, explicit: str | None
) -> Path:
    if explicit:
        candidates = [Path(explicit).expanduser().resolve()]
    else:
        resolved = Path(pi_bin).resolve()
        candidates = [resolved.parent, resolved.parent.parent, *resolved.parents]
    checked: set[Path] = set()
    for candidate in candidates:
        if candidate in checked:
            continue
        checked.add(candidate)
        package_json = candidate / "package.json"
        sdk_index = candidate / "dist" / "index.js"
        try:
            metadata = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (
            metadata.get("name") == "@earendil-works/pi-coding-agent"
            and sdk_index.is_file()
        ):
            return candidate
    parser.error(
        "could not locate @earendil-works/pi-coding-agent SDK from the pi executable; "
        "install the npm Pi package or pass --package-dir"
    )


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def sanitize_progress_event(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("type") != "progress":
        return None
    stage = value.get("stage")
    if not isinstance(stage, str) or not stage or len(stage) > 64:
        return None
    sanitized: dict[str, Any] = {"stage": stage}
    integer_fields = (
        "sequence",
        "emitted_at_ms",
        "elapsed_ms",
        "pi_task_invocations",
        "provider_request_count",
        "retry_events",
        "agent_start_events",
        "agent_end_events",
        "tool_start_events",
        "tool_end_events",
        "assistant_text_bytes",
    )
    for field in integer_fields:
        item = value.get(field)
        if isinstance(item, int) and item >= 0:
            sanitized[field] = item
    last_event_type = value.get("last_event_type")
    if isinstance(last_event_type, str) and 0 < len(last_event_type) <= 64:
        sanitized["last_event_type"] = last_event_type
    for field in ("invocation_id", "pi_session_id"):
        item = value.get(field)
        if isinstance(item, str) and UUID_PATTERN.fullmatch(item):
            sanitized[field] = item.lower()
    return sanitized


def parse_bridge_output(stdout: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    progress: list[dict[str, Any]] = []
    envelope: dict[str, Any] | None = None
    nonempty_lines = [line for line in stdout.splitlines() if line.strip()]
    for index, line in enumerate(nonempty_lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"bridge output line {index + 1} is not valid JSON: {exc}") from exc
        event = sanitize_progress_event(value)
        if event is not None:
            if envelope is not None:
                raise ValueError("progress event appeared after the result envelope")
            progress.append(event)
            continue
        if not isinstance(value, dict) or value.get("type") != "result":
            raise ValueError(f"bridge output line {index + 1} is not a progress or result object")
        if envelope is not None:
            raise ValueError("bridge emitted more than one result envelope")
        envelope = value
    if envelope is None:
        raise ValueError("bridge output does not contain a result envelope")
    return envelope, progress


def progress_snapshot_from_bytes(stdout: bytes) -> tuple[dict[str, Any] | None, int]:
    try:
        decoded = stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None, 0
    events: list[dict[str, Any]] = []
    for line in decoded.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = sanitize_progress_event(value)
        if event is not None:
            events.append(event)
    if not events:
        return None, 0
    snapshot = dict(events[-1])
    emitted_at_ms = snapshot.get("emitted_at_ms")
    if isinstance(emitted_at_ms, int):
        snapshot["last_progress_age_ms"] = max(
            0, int(time.time() * 1000) - emitted_at_ms
        )
    return snapshot, len(events)


def run_bridge(
    node_bin: str,
    bridge: Path,
    cwd: Path,
    request: bytes,
    timeout_policy: TimeoutPolicy,
) -> tuple[int, bytes, bytes]:
    try:
        process = subprocess.Popen(
            [node_bin, str(bridge)],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        fail(
            "pi_bridge_spawn_failure",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            pi_task_invocations=0,
            error=bounded_text(str(exc)),
        )
    try:
        stdout, stderr = process.communicate(
            input=request, timeout=timeout_policy.wall_timeout_seconds
        )
    except subprocess.TimeoutExpired as exc:
        terminate_process_group(process)
        try:
            stdout, stderr = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            stdout = exc.output or b""
            stderr = exc.stderr or b""
        last_progress, progress_event_count = progress_snapshot_from_bytes(stdout)
        fail(
            "pi_task_timeout",
            EXIT_TIMEOUT,
            outcome="unknown",
            pi_task_invocations=1,
            timeout_scope="task_wall_clock",
            timeout_policy=timeout_policy.diagnostic(),
            progress_event_count=progress_event_count,
            last_progress=last_progress,
            stdout_bytes=len(stdout),
            stdout_sha256=sha256_bytes(stdout),
            stderr_bytes=len(stderr),
            stderr_sha256=sha256_bytes(stderr),
        )
    return process.returncode, stdout, stderr


def decode_capture(
    returncode: int, stdout: bytes, stderr: bytes, max_capture_bytes: int
) -> tuple[str, str]:
    if len(stdout) > max_capture_bytes or len(stderr) > max_capture_bytes:
        fail(
            "pi_capture_limit",
            EXIT_CAPTURE_LIMIT,
            outcome="unknown",
            pi_task_invocations=1,
            bridge_exit_code=returncode,
            max_capture_bytes=max_capture_bytes,
            stdout_bytes=len(stdout),
            stdout_sha256=sha256_bytes(stdout),
            stderr_bytes=len(stderr),
            stderr_sha256=sha256_bytes(stderr),
        )
    try:
        return stdout.decode("utf-8"), stderr.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(
            "pi_invalid_utf8",
            EXIT_INVALID_OUTPUT,
            outcome="unknown",
            pi_task_invocations=1,
            bridge_exit_code=returncode,
            error=bounded_text(str(exc)),
            stdout_bytes=len(stdout),
            stdout_sha256=sha256_bytes(stdout),
            stderr_bytes=len(stderr),
            stderr_sha256=sha256_bytes(stderr),
        )


def validate_success(
    envelope: dict[str, Any], args: argparse.Namespace, tools: list[str]
) -> str | None:
    expected = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "pi_task_invocations": 1,
        "retry_events": 0,
        "agent_start_events": 1,
        "agent_end_events": 1,
        "stop_reason": "stop",
    }
    for field, expected_value in expected.items():
        if envelope.get(field) != expected_value:
            return f"field {field!r} does not match expected value {expected_value!r}"
    for field in ("invocation_id", "pi_session_id"):
        expected_value = getattr(args, field)
        if envelope.get(field) != expected_value:
            return f"field {field!r} does not match the controller allocation"
    for field in ("provider", "model"):
        value = envelope.get(field)
        if not isinstance(value, str) or not value:
            return f"field {field!r} must be a non-empty string"
    if args.provider is not None and envelope["provider"] != args.provider:
        return "provider does not match the explicit override"
    if args.model is not None and envelope["model"] != args.model:
        return "model does not match the explicit override"
    thinking_level = envelope.get("thinking_level")
    if thinking_level not in THINKING_LEVELS:
        return "thinking_level is not supported"
    if args.effort is not None and thinking_level != args.effort:
        return "thinking_level does not match the explicit effort"
    if not isinstance(envelope.get("provider_request_count"), int) or envelope[
        "provider_request_count"
    ] <= 0:
        return "provider_request_count must be a positive integer"
    if not tools and envelope["provider_request_count"] != 1:
        return "no-tool mode must make exactly one provider request"
    tool_events = envelope.get("tool_events")
    if not isinstance(tool_events, list) or any(not isinstance(item, str) for item in tool_events):
        return "tool_events must be a list of strings"
    if set(tool_events) - set(tools):
        return "tool_events contains an unauthorized tool"
    result = envelope.get("result")
    if not isinstance(result, str) or not result.strip():
        return "result must be a non-empty string"
    return None


def failure_exit_code(kind: Any) -> int:
    if kind == "pi_permission_denied":
        return EXIT_PERMISSION_DENIED
    if kind in {"pi_model_not_found", "pi_model_mismatch", "pi_thinking_mismatch"}:
        return EXIT_MODEL_UNAVAILABLE
    if kind in {"pi_sdk_import_failed", "pi_sdk_incompatible", "pi_bridge_failure"}:
        return EXIT_SPAWN_FAILURE
    if kind == "pi_result_limit":
        return EXIT_CAPTURE_LIMIT
    return EXIT_SEMANTIC_FAILURE


def main() -> int:
    global _ACTIVE_RECEIPT
    parser = build_parser()
    args = parser.parse_args()
    args.invocation_id = str(uuid.uuid4())
    args.pi_session_id = str(uuid.uuid4())
    if (args.provider is None) != (args.model is None):
        parser.error("--provider and --model must be supplied together")

    tools = normalize_tools(args, parser)
    try:
        timeout_policy = build_timeout_policy(
            mode=args.mode,
            tools=tools,
            effort=args.effort,
            wall_timeout_seconds=args.wall_timeout_seconds,
            provider_timeout_seconds=args.provider_timeout_seconds,
            stream_idle_timeout_seconds=args.stream_idle_timeout_seconds,
            allow_short_timeout=args.allow_short_timeout,
        )
    except TimeoutPolicyError as exc:
        fail(
            "pi_timeout_policy_violation",
            EXIT_USAGE,
            outcome="not_started",
            pi_task_invocations=0,
            error=bounded_text(str(exc)),
            **exc.details,
        )

    cwd = Path(args.cwd).expanduser()
    if not cwd.is_dir():
        parser.error(f"--cwd is not a directory: {cwd}")
    cwd = cwd.resolve()

    node_bin = shutil.which("node")
    pi_bin = shutil.which("pi")
    if not node_bin or not pi_bin:
        missing = "node" if not node_bin else "pi"
        fail(
            "pi_dependency_not_found",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            pi_task_invocations=0,
            dependency=missing,
        )

    package_dir = locate_package_dir(parser, pi_bin, args.package_dir)
    bridge = Path(__file__).with_name("pi-agent-bridge.mjs")
    if not bridge.is_file():
        fail(
            "pi_bridge_not_found",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            pi_task_invocations=0,
            bridge=str(bridge),
        )

    prompt = build_prompt(args, parser)
    prompt_bytes = prompt.encode("utf-8")
    if len(prompt_bytes) > args.max_input_bytes:
        fail(
            "pi_input_limit",
            EXIT_CAPTURE_LIMIT,
            outcome="not_started",
            pi_task_invocations=0,
            max_input_bytes=args.max_input_bytes,
            input_bytes=len(prompt_bytes),
            input_sha256=sha256_bytes(prompt_bytes),
        )

    receipt_directory = Path(args.receipt_dir)
    initial_receipt = {
        "invocation_id": args.invocation_id,
        "pi_session_id": args.pi_session_id,
        "created_at": utc_now(),
        "outcome": "running",
        "mode": args.mode,
        "cwd_sha256": sha256_bytes(str(cwd).encode("utf-8")),
        "input_bytes": len(prompt_bytes),
        "input_sha256": sha256_bytes(prompt_bytes),
        "requested_provider": args.provider,
        "requested_model": args.model,
        "requested_thinking_level": args.effort,
        "tools": tools,
        "timeout_policy": timeout_policy.diagnostic(),
    }
    try:
        _ACTIVE_RECEIPT = ReceiptWriter(receipt_directory, initial_receipt)
    except OSError as exc:
        fail(
            "pi_receipt_write_failed",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            pi_task_invocations=0,
            invocation_id=args.invocation_id,
            pi_session_id=args.pi_session_id,
            receipt_path=str(receipt_directory / f"{args.invocation_id}.json"),
            error=bounded_text(str(exc)),
        )

    request = json.dumps(
        {
            "invocation_id": args.invocation_id,
            "pi_session_id": args.pi_session_id,
            "package_dir": str(package_dir),
            "cwd": str(cwd),
            "provider": args.provider,
            "model": args.model,
            "thinking_level": args.effort,
            "prompt": prompt,
            "tools": tools,
            "provider_timeout_ms": timeout_policy.provider_timeout_seconds * 1000,
            "stream_idle_timeout_ms": timeout_policy.stream_idle_timeout_seconds * 1000,
            "max_result_bytes": args.max_result_bytes,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    returncode, stdout_bytes, stderr_bytes = run_bridge(
        node_bin, bridge, cwd, request, timeout_policy
    )
    stdout, stderr = decode_capture(
        returncode, stdout_bytes, stderr_bytes, args.max_capture_bytes
    )
    try:
        envelope, progress_events = parse_bridge_output(stdout)
    except ValueError as exc:
        last_progress, progress_event_count = progress_snapshot_from_bytes(stdout_bytes)
        details: dict[str, Any] = {
            "outcome": "unknown",
            "pi_task_invocations": 1,
            "bridge_exit_code": returncode,
            "error": bounded_text(str(exc)),
            "timeout_policy": timeout_policy.diagnostic(),
            "progress_event_count": progress_event_count,
            "last_progress": last_progress,
            "stdout_characters": len(stdout),
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        }
        if stderr:
            details["stderr"] = bounded_text(stderr)
        fail("pi_invalid_json", EXIT_INVALID_OUTPUT, **details)

    for field in ("invocation_id", "pi_session_id"):
        if envelope.get(field) != getattr(args, field):
            fail(
                "pi_trace_mismatch",
                EXIT_INVALID_OUTPUT,
                outcome="unknown",
                pi_task_invocations=1,
                bridge_exit_code=returncode,
                validation_error=bounded_text(
                    f"bridge field {field!r} does not match the controller allocation"
                ),
            )

    success_error = validate_success(envelope, args, tools)
    if returncode == 0 and success_error is None and not stderr:
        result = envelope["result"]
        if args.mode == "doctor" and result != EXPECTED_DOCTOR_RESULT:
            encoded = result.encode("utf-8")
            fail(
                "pi_doctor_mismatch",
                EXIT_INVALID_OUTPUT,
                outcome="failed",
                pi_task_invocations=1,
                result_bytes=len(encoded),
                result_sha256=sha256_bytes(encoded),
            )
        encoded = result.encode("utf-8")
        try:
            _ACTIVE_RECEIPT.finalize(
                outcome="success",
                provider=envelope["provider"],
                model=envelope["model"],
                thinking_level=envelope["thinking_level"],
                pi_task_invocations=envelope["pi_task_invocations"],
                provider_request_count=envelope["provider_request_count"],
                retry_events=envelope["retry_events"],
                agent_start_events=envelope["agent_start_events"],
                agent_end_events=envelope["agent_end_events"],
                stop_reason=envelope["stop_reason"],
                result_bytes=len(encoded),
                result_sha256=sha256_bytes(encoded),
            )
        except OSError as exc:
            fail(
                "pi_receipt_write_failed",
                EXIT_INVALID_OUTPUT,
                outcome="unknown",
                pi_task_invocations=1,
                error=bounded_text(str(exc)),
                result_bytes=len(encoded),
                result_sha256=sha256_bytes(encoded),
            )
        if args.output_format == "json":
            output = {
                "type": "pi_task_result",
                "result": result,
                "trace": {
                    **_ACTIVE_RECEIPT.trace(),
                    "outcome": "success",
                    "provider": envelope["provider"],
                    "model": envelope["model"],
                    "thinking_level": envelope["thinking_level"],
                    "provider_request_count": envelope["provider_request_count"],
                },
            }
            sys.stdout.write(json.dumps(output, ensure_ascii=False, sort_keys=True) + "\n")
        else:
            sys.stdout.write(result)
            if not result.endswith("\n"):
                sys.stdout.write("\n")
        return 0

    if envelope.get("subtype") == "error" and envelope.get("is_error") is True:
        diagnostic = {
            key: bounded_json(value)
            for key, value in envelope.items()
            if key != "result" and value is not None
        }
        diagnostic["bridge_exit_code"] = returncode
        diagnostic["timeout_policy"] = timeout_policy.diagnostic()
        diagnostic["progress_event_count"] = len(progress_events)
        if progress_events:
            diagnostic["last_progress"] = progress_events[-1]
        if stderr:
            diagnostic["bridge_stderr"] = bounded_text(stderr)
        if diagnostic.get("auth_state") == "unknown" or AUTH_PATTERN.search(
            json.dumps(diagnostic.get("error", ""), ensure_ascii=False)
        ):
            diagnostic["auth_state"] = "unknown"
            diagnostic["user_action"] = (
                "Run pi interactively and use /login, or configure the provider credential; "
                "then confirm before retrying."
            )
        fail(
            str(envelope.get("kind") or "pi_request_failed"),
            failure_exit_code(envelope.get("kind")),
            **{key: value for key, value in diagnostic.items() if key != "kind"},
        )

    fail(
        "pi_invalid_envelope",
        EXIT_INVALID_OUTPUT,
        outcome="unknown",
        pi_task_invocations=1,
        bridge_exit_code=returncode,
        validation_error=bounded_text(success_error or "unexpected bridge state"),
        envelope=bounded_json(envelope),
        stderr=bounded_text(stderr) if stderr else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
