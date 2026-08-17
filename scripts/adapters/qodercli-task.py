#!/usr/bin/env python3
"""Run one Qoder CLI task, validate it in memory, and emit only result."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, NoReturn


EXIT_SEMANTIC_FAILURE = 1
EXIT_INVALID_OUTPUT = 65
EXIT_SPAWN_FAILURE = 70
EXIT_CAPTURE_LIMIT = 74
EXIT_TIMEOUT = 75
EXIT_PERMISSION_DENIED = 77
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_MAX_CAPTURE_BYTES = 8 * 1024 * 1024
DEFAULT_SHELL_ENV_TIMEOUT_SECONDS = 60
DEFAULT_MAX_SHELL_ENV_BYTES = 1024 * 1024
ERROR_TEXT_LIMIT = 4096
READ_ONLY_TOOLS = {"Read", "Grep", "Glob"}
AUTH_LINE_PATTERN = re.compile(
    r"(?:not logged in)(?:\s*[·:;—-]\s*please run /login)?|please run /login",
    re.IGNORECASE,
)


class EnvelopeParseError(ValueError):
    """Raised when captured qodercli output is not a valid result envelope."""


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def bounded_text(value: str, limit: int = ERROR_TEXT_LIMIT) -> dict[str, Any]:
    if len(value) <= limit:
        return {"text": value, "truncated": False}
    return {
        "text": value[:limit],
        "truncated": True,
        "characters": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
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


def fail(kind: str, exit_code: int, **details: Any) -> NoReturn:
    outcome = details.pop("outcome", "unknown")
    invocations = details.pop(
        "backend_task_invocations", details.pop("qodercli_task_invocations", 0)
    )
    payload = {
        "type": "independent_review_adapter_diagnostic",
        "kind": kind,
        "outcome": outcome,
        "backend_task_invocations": invocations,
        "details": {"original_request_retried": False, **details},
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    raise SystemExit(exit_code)


class DiagnosticParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        fail("invalid_arguments", 64, outcome="not_started", error=bounded_text(message))


def build_parser() -> argparse.ArgumentParser:
    parser = DiagnosticParser(
        description=(
            "Run one qodercli task in the current process environment, "
            "capture JSON in memory, validate it, and print only result."
        )
    )
    parser.add_argument("mode", choices=("prompt",))
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--tools")
    parser.add_argument("--max-output-tokens", type=positive_int, default=4096)
    parser.add_argument("--agent", default="general-purpose")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--shell-env", choices=("login-zsh", "inherit"))
    parser.add_argument(
        "--timeout-seconds", type=positive_int, default=DEFAULT_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--max-capture-bytes", type=positive_int, default=DEFAULT_MAX_CAPTURE_BYTES
    )
    return parser


def read_utf8_file(parser: argparse.ArgumentParser, value: str, label: str) -> str:
    path = Path(value)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        parser.error(f"{label} is not readable: {path}: {exc}")
    if not text.strip():
        parser.error(f"{label} is empty: {path}")
    return text


def build_prompt(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    return read_utf8_file(parser, args.prompt_file, "prompt file")


def normalize_tools(args: argparse.Namespace) -> list[str]:
    if args.tools is None:
        return []
    tools = [item for item in re.split(r"[\s,]+", args.tools.strip()) if item]
    unsupported = sorted(set(tools) - READ_ONLY_TOOLS)
    if unsupported:
        raise ValueError(
            "unsupported non-read-only tools: " + ", ".join(unsupported)
        )
    return tools


def build_command(
    qodercli_bin: str, args: argparse.Namespace, cwd: Path, prompt: str
) -> list[str]:
    command = [qodercli_bin, "-p"]
    if args.model:
        command.extend(["-m", args.model])
    command.extend(
        [
            "--cwd",
            str(cwd),
            "--agent",
            args.agent,
            "--output-format",
            "json",
            "--max-output-tokens",
            str(args.max_output_tokens),
            "--permission-mode",
            "dont_ask",
        ]
    )
    command.extend(["--no-session-persistence", "--max-model-request-retries", "0"])
    if args.reasoning_effort:
        command.extend(["--reasoning-effort", args.reasoning_effort])

    tools = normalize_tools(args)
    if tools:
        command.extend(["--tools", *tools, "--allowed-tools", ",".join(tools)])
    else:
        command.extend(["--tools", ""])
    command.extend(["--", prompt])
    return command


def half_arg_max_limit() -> int:
    try:
        argument_max = int(os.sysconf("SC_ARG_MAX"))
    except (AttributeError, OSError, TypeError, ValueError):
        argument_max = 262_144
    return max(65_536, argument_max // 2)


def login_zsh_environment(base_env: dict[str, str]) -> dict[str, str]:
    zsh_bin = shutil.which("zsh", path=base_env.get("PATH"))
    if not zsh_bin:
        fail("login_zsh_not_found", EXIT_SPAWN_FAILURE, outcome="not_started")
    try:
        completed = subprocess.run(
            [zsh_bin, "-lic", "exec /usr/bin/env -0"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=DEFAULT_SHELL_ENV_TIMEOUT_SECONDS,
            env=base_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(
            "login_zsh_failed",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            error=bounded_text(str(exc)),
        )
    if completed.returncode != 0:
        fail(
            "login_zsh_failed",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            shell_exit_code=completed.returncode,
            shell_stderr_bytes=len(completed.stderr),
            shell_stderr_sha256=sha256_bytes(completed.stderr),
        )
    if len(completed.stdout) > DEFAULT_MAX_SHELL_ENV_BYTES:
        fail(
            "login_zsh_environment_limit",
            EXIT_CAPTURE_LIMIT,
            outcome="not_started",
            max_shell_env_bytes=DEFAULT_MAX_SHELL_ENV_BYTES,
            shell_env_bytes=len(completed.stdout),
            shell_env_sha256=sha256_bytes(completed.stdout),
        )
    environment: dict[str, str] = {}
    try:
        for entry in completed.stdout.rstrip(b"\0").split(b"\0"):
            if not entry:
                continue
            raw_key, raw_value = entry.split(b"=", 1)
            key = os.fsdecode(raw_key)
            if not key or "=" in key or "\0" in key:
                raise ValueError("invalid environment key")
            environment[key] = os.fsdecode(raw_value)
    except (ValueError, TypeError) as exc:
        fail(
            "login_zsh_environment_invalid",
            EXIT_INVALID_OUTPUT,
            outcome="not_started",
            error=bounded_text(str(exc)),
        )
    if not environment:
        fail("login_zsh_environment_empty", EXIT_INVALID_OUTPUT, outcome="not_started")
    return environment


def run_process(
    command: list[str], cwd: Path, timeout_seconds: int, env: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            start_new_session=True,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        fail(
            "qodercli_timeout",
            EXIT_TIMEOUT,
            outcome="unknown",
            qodercli_task_invocations=1,
            timeout_seconds=timeout_seconds,
            stdout_bytes=len(stdout),
            stdout_sha256=sha256_bytes(stdout),
            stderr_bytes=len(stderr),
            stderr_sha256=sha256_bytes(stderr),
        )
    except OSError as exc:
        fail(
            "qodercli_spawn_failure",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            qodercli_task_invocations=0,
            error=bounded_text(str(exc)),
        )


def decode_capture(
    completed: subprocess.CompletedProcess[bytes], max_capture_bytes: int
) -> tuple[str, str]:
    stdout = completed.stdout
    stderr = completed.stderr
    if len(stdout) > max_capture_bytes or len(stderr) > max_capture_bytes:
        fail(
            "qodercli_capture_limit",
            EXIT_CAPTURE_LIMIT,
            outcome="unknown",
            qodercli_task_invocations=1,
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
            "qodercli_invalid_utf8",
            EXIT_INVALID_OUTPUT,
            outcome="unknown",
            qodercli_task_invocations=1,
            error=bounded_text(str(exc)),
            stdout_bytes=len(stdout),
            stdout_sha256=sha256_bytes(stdout),
            stderr_bytes=len(stderr),
            stderr_sha256=sha256_bytes(stderr),
        )


def parse_envelope(output_format: str, stdout: str) -> dict[str, Any]:
    try:
        if output_format == "json":
            value = json.loads(stdout)
            if not isinstance(value, dict):
                raise ValueError("JSON output is not an object")
            return value

        messages: list[dict[str, Any]] = []
        for line_number, line in enumerate(stdout.splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"stream line {line_number} is not an object")
            messages.append(value)
        if not messages or messages[-1].get("type") != "result":
            raise ValueError("stream-json output has no final result message")
        return messages[-1]
    except (json.JSONDecodeError, ValueError) as exc:
        raise EnvelopeParseError(str(exc)) from exc


def looks_like_auth_failure(envelope: dict[str, Any], stderr: str) -> bool:
    if envelope.get("is_error") is not True or envelope.get("permission_denials"):
        return False
    candidates: list[str] = []
    result = envelope.get("result")
    if isinstance(result, str):
        candidates.append(result)
    errors = envelope.get("errors")
    if isinstance(errors, list):
        candidates.extend(item for item in errors if isinstance(item, str))
    if stderr:
        candidates.append(stderr)
    return any(AUTH_LINE_PATTERN.fullmatch(item.strip()) for item in candidates)


def looks_like_unstructured_auth_failure(
    completed: subprocess.CompletedProcess[bytes], stdout: str, stderr: str
) -> bool:
    if completed.returncode == 0:
        return False
    candidates = [stdout.strip(), *(line.strip() for line in stderr.splitlines())]
    return any(
        candidate and AUTH_LINE_PATTERN.fullmatch(candidate)
        for candidate in candidates
    )


def probe_auth_state(qodercli_bin: str, cwd: Path, env: dict[str, str]) -> str:
    try:
        completed = subprocess.run(
            [qodercli_bin, "status", "--output", "json"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=30,
            start_new_session=True,
            env=env,
        )
        if completed.returncode != 0:
            return "unknown"
        value = json.loads(completed.stdout.decode("utf-8"))
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(value, dict):
        return "unknown"
    logged_in = value.get("logged_in")
    if logged_in is True:
        return "logged_in"
    if logged_in is False:
        return "logged_out"
    return "unknown"


def failure_details(
    completed: subprocess.CompletedProcess[bytes],
    envelope: dict[str, Any],
    stderr: str,
    auth_state: str | None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "outcome": "failed",
        "qodercli_task_invocations": 1,
        "qodercli_exit_code": completed.returncode,
        "type": envelope.get("type"),
        "subtype": envelope.get("subtype"),
        "is_error": envelope.get("is_error"),
        "error_code": envelope.get("error_code"),
        "errors": bounded_json(envelope.get("errors") or []),
        "permission_denials": bounded_json(envelope.get("permission_denials") or []),
    }
    if envelope.get("is_error") and isinstance(envelope.get("result"), str):
        details["result"] = bounded_text(envelope["result"])
    if stderr:
        details["stderr"] = bounded_text(stderr)
    if auth_state is not None:
        details["auth_state"] = auth_state
        details["user_action"] = auth_user_action(auth_state)
    return details


def auth_user_action(auth_state: str) -> str:
    if auth_state == "logged_out":
        return "Run qodercli login manually, then confirm before retrying."
    if auth_state == "logged_in":
        return "Treat as a transient/headless mismatch; ask before retrying."
    return "Auth state is unknown; do not claim logout or retry automatically."


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    cwd = Path(args.cwd).expanduser()
    if not cwd.is_dir():
        parser.error(f"--cwd is not a directory: {cwd}")
    cwd = cwd.resolve()

    prompt = build_prompt(args, parser)
    prompt_bytes = prompt.encode("utf-8")
    safe_limit = half_arg_max_limit()
    if len(prompt_bytes) > safe_limit:
        fail(
            "argument_limit",
            EXIT_CAPTURE_LIMIT,
            outcome="not_started",
            safe_prompt_limit_bytes=safe_limit,
            prompt_bytes=len(prompt_bytes),
            prompt_sha256=sha256_bytes(prompt_bytes),
        )

    shell_mode = args.shell_env or os.environ.get(
        "INDEPENDENT_REVIEW_QODER_SHELL_ENV", "login-zsh"
    )
    if shell_mode not in {"login-zsh", "inherit"}:
        fail(
            "invalid_shell_env",
            64,
            outcome="not_started",
            value=bounded_text(shell_mode),
        )
    runtime_env = os.environ.copy()
    if shell_mode == "login-zsh":
        runtime_env = login_zsh_environment(runtime_env)

    qodercli_bin = shutil.which("qodercli", path=runtime_env.get("PATH"))
    if not qodercli_bin:
        fail(
            "qodercli_not_found",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            qodercli_task_invocations=0,
        )

    try:
        command = build_command(qodercli_bin, args, cwd, prompt)
    except ValueError as exc:
        parser.error(str(exc))
    completed = run_process(command, cwd, args.timeout_seconds, runtime_env)
    stdout, stderr = decode_capture(completed, args.max_capture_bytes)
    try:
        envelope = parse_envelope("json", stdout)
    except EnvelopeParseError as exc:
        auth_state: str | None = None
        if looks_like_unstructured_auth_failure(completed, stdout, stderr):
            auth_state = probe_auth_state(qodercli_bin, cwd, runtime_env)
        details: dict[str, Any] = {
            "outcome": "unknown",
            "qodercli_task_invocations": 1,
            "qodercli_exit_code": completed.returncode,
            "error": bounded_text(str(exc)),
            "stdout_characters": len(stdout),
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        }
        if stderr:
            details["stderr"] = bounded_text(stderr)
        if auth_state is not None:
            details["auth_state"] = auth_state
            details["user_action"] = auth_user_action(auth_state)
        fail("qodercli_invalid_json", EXIT_INVALID_OUTPUT, **details)

    permission_denials = envelope.get("permission_denials", [])
    if not isinstance(permission_denials, list):
        fail(
            "qodercli_invalid_envelope",
            EXIT_INVALID_OUTPUT,
            outcome="unknown",
            qodercli_task_invocations=1,
            qodercli_exit_code=completed.returncode,
            field="permission_denials",
            actual_type=type(permission_denials).__name__,
        )
    semantic_success = (
        envelope.get("type") == "result"
        and envelope.get("subtype") == "success"
        and envelope.get("is_error") is False
        and isinstance(envelope.get("result"), str)
        and not permission_denials
    )
    if completed.returncode == 0 and semantic_success:
        result = envelope["result"]
        sys.stdout.write(result)
        if not result.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    auth_state: str | None = None
    if looks_like_auth_failure(envelope, stderr):
        auth_state = probe_auth_state(qodercli_bin, cwd, runtime_env)

    details = failure_details(completed, envelope, stderr, auth_state)
    if permission_denials:
        fail("qodercli_permission_denied", EXIT_PERMISSION_DENIED, **details)
    fail("qodercli_request_failed", EXIT_SEMANTIC_FAILURE, **details)


if __name__ == "__main__":
    raise SystemExit(main())
