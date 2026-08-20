#!/usr/bin/env python3
"""Run one dsh --profile headless task with a read-only posture and emit review text.

dsh has no prompt-file or stdin transport and no JSON terminal envelope. This
adapter therefore carries the prompt as one bounded argv item, runs from an
empty scratch workspace, applies a review-only patch, and prints dsh stdout
as natural review text for the dispatcher's standard verdict extraction.
"""

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
import tempfile
from typing import Any, NoReturn


EXIT_SEMANTIC_FAILURE = 1
EXIT_INVALID_OUTPUT = 65
EXIT_SPAWN_FAILURE = 70
EXIT_CAPTURE_LIMIT = 74
DEFAULT_MAX_INPUT_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_SINGLE_ARGUMENT_BYTES = 120 * 1024
ERROR_TEXT_LIMIT = 4096
PATCH_FILENAME = "dsh-review.patch.yml"
AUTH_PATTERN = re.compile(
    r"(?:api[ _-]?key|authentication|unauthorized|not logged in|credentials?|\b401\b)",
    re.IGNORECASE,
)


class DiagnosticParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        fail("invalid_arguments", 64, outcome="not_started", error=bounded_text(message))


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def bounded_text(value: str, limit: int = ERROR_TEXT_LIMIT) -> dict[str, Any]:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return {"text": value, "truncated": False, "bytes": len(encoded)}
    prefix = encoded[:limit].decode("utf-8", errors="replace")
    return {
        "text": prefix,
        "truncated": True,
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def fail(kind: str, exit_code: int, **details: Any) -> NoReturn:
    outcome = details.pop("outcome", "unknown")
    invocations = details.pop(
        "backend_task_invocations", details.pop("dsh_task_invocations", 0)
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


def build_parser() -> argparse.ArgumentParser:
    parser = DiagnosticParser(
        description=(
            "Run one dsh --profile headless task, keep it read-only, and print "
            "only the final assistant text."
        )
    )
    parser.add_argument("mode", choices=("prompt",))
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument(
        "--evidence-mode",
        choices=("paths",),
        help="review-paths marker from the bundled profile; absent for tool-free modes",
    )
    parser.add_argument("--dsh-bin")
    parser.add_argument(
        "--max-input-bytes", type=positive_int, default=DEFAULT_MAX_INPUT_BYTES
    )
    parser.add_argument(
        "--max-capture-bytes", type=positive_int, default=DEFAULT_MAX_CAPTURE_BYTES
    )
    return parser


def read_utf8_file(
    parser: argparse.ArgumentParser, value: str, label: str, max_bytes: int
) -> str:
    path = Path(value)
    try:
        data = path.read_bytes()
    except OSError as exc:
        parser.error(f"{label} is not readable: {path}: {exc}")
    if len(data) > max_bytes:
        fail(
            "dsh_input_limit",
            EXIT_CAPTURE_LIMIT,
            outcome="not_started",
            dsh_task_invocations=0,
            label=label,
            max_input_bytes=max_bytes,
            input_bytes=len(data),
            input_sha256=sha256_bytes(data),
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        parser.error(f"{label} is not valid UTF-8: {path}: {exc}")
    if not text.strip():
        parser.error(f"{label} is empty: {path}")
    return text


def half_arg_max_limit() -> int:
    """Keep the one prompt argument below both ARG_MAX and common per-arg caps."""
    try:
        argument_max = int(os.sysconf("SC_ARG_MAX"))
    except (AttributeError, OSError, TypeError, ValueError):
        argument_max = 262_144
    return max(1, min(argument_max // 2, MAX_SINGLE_ARGUMENT_BYTES))


def resolve_executable(explicit: str | None, name: str) -> str | None:
    if explicit is None:
        return shutil.which(name)
    candidate = Path(explicit).expanduser()
    if not candidate.is_absolute():
        return None
    try:
        candidate.resolve(strict=True)
    except OSError:
        return None
    if candidate.name != name or not candidate.is_file() or not os.access(candidate, os.X_OK):
        return None
    return str(candidate)


def review_home() -> Path:
    """Return the trusted, review-specific Harness home."""
    override = os.environ.get("INDEPENDENT_REVIEW_DSH_HOME")
    if override:
        return Path(override).expanduser().resolve()
    config_root = os.environ.get("INDEPENDENT_REVIEW_HOME")
    if config_root:
        return (Path(config_root).expanduser() / "dsh").resolve()
    return (Path("~/.config/independent-review").expanduser() / "dsh").resolve()


def roots_overlap(first: Path, second: Path) -> bool:
    """Return whether two resolved trust roots contain one another."""
    return first == second or first in second.parents or second in first.parents


def runtime_environment(isolated_home: Path | None = None) -> dict[str, str]:
    """Replace ambient dsh controls with the review adapter's fixed posture."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("DSH_")}
    isolated_home = isolated_home or review_home()
    env["DSH_HOME"] = str(isolated_home)
    env["DSH_AGENTS_HOME"] = str(isolated_home / "agents")
    env["DSH_PERMISSION_MODE"] = "read-only"
    env["DSH_TELEMETRY_DISABLED"] = "1"
    return env


def build_direct_command(dsh_bin: str, patch_path: Path, prompt: str) -> list[str]:
    command = [dsh_bin, "--profile", "headless"]
    command.extend(["--patch", str(patch_path)])
    command.append(prompt)
    return command


def add_review_root(prompt: str, cwd: Path) -> str:
    """Tell a scratch-workspace reviewer where relative trusted paths begin."""
    root = json.dumps(str(cwd), ensure_ascii=True)
    return (
        "Adapter execution context: the trusted repository root is the JSON "
        f"string {root}. Resolve relative reviewed paths and symbols against "
        "that root, and do not inspect outside it.\n\n"
        + prompt
    )


def run_process(
    command: list[str], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        fail(
            "dsh_spawn_failure",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            dsh_task_invocations=0,
            error=bounded_text(str(exc)),
        )


def decode_capture(
    completed: subprocess.CompletedProcess[bytes], max_capture_bytes: int
) -> tuple[str, str]:
    stdout = completed.stdout
    stderr = completed.stderr
    if len(stdout) > max_capture_bytes or len(stderr) > max_capture_bytes:
        fail(
            "dsh_capture_limit",
            EXIT_CAPTURE_LIMIT,
            outcome="unknown",
            dsh_task_invocations=1,
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
            "dsh_invalid_utf8",
            EXIT_INVALID_OUTPUT,
            outcome="unknown",
            dsh_task_invocations=1,
            dsh_exit_code=completed.returncode,
            error=bounded_text(str(exc)),
            stdout_bytes=len(stdout),
            stdout_sha256=sha256_bytes(stdout),
            stderr_bytes=len(stderr),
            stderr_sha256=sha256_bytes(stderr),
        )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    cwd = Path(args.cwd).expanduser()
    if not cwd.is_dir():
        parser.error(f"--cwd is not a directory: {cwd}")
    cwd = cwd.resolve()

    isolated_home = review_home()
    if roots_overlap(isolated_home, cwd):
        fail(
            "dsh_home_inside_checkout",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            dsh_task_invocations=0,
            dsh_home=str(isolated_home),
            cwd=str(cwd),
        )

    prompt = read_utf8_file(parser, args.prompt_file, "prompt file", args.max_input_bytes)
    if args.evidence_mode == "paths":
        prompt = add_review_root(prompt, cwd)
    prompt_bytes = prompt.encode("utf-8")
    safe_limit = half_arg_max_limit()
    if len(prompt_bytes) > safe_limit:
        fail(
            "dsh_argument_limit",
            EXIT_CAPTURE_LIMIT,
            outcome="not_started",
            dsh_task_invocations=0,
            safe_prompt_limit_bytes=safe_limit,
            prompt_bytes=len(prompt_bytes),
            prompt_sha256=sha256_bytes(prompt_bytes),
        )

    dsh_bin = resolve_executable(args.dsh_bin, "dsh")
    if dsh_bin is None:
        fail(
            "dsh_not_found",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            dsh_task_invocations=0,
            dependency="dsh",
        )

    patch_path = Path(__file__).with_name(PATCH_FILENAME)
    if not patch_path.is_file():
        fail(
            "dsh_patch_not_found",
            EXIT_SPAWN_FAILURE,
            outcome="not_started",
            dsh_task_invocations=0,
            patch=str(patch_path),
        )

    scratch: tempfile.TemporaryDirectory[str] | None = None
    try:
        # Every mode starts outside the reviewed checkout. This prevents dsh's
        # launcher from ingesting checkout .env files, AGENTS.md, project skills,
        # and other workspace-owned ambient context before the overlay activates.
        try:
            scratch = tempfile.TemporaryDirectory(prefix="independent-review-dsh-")
        except OSError as exc:
            fail(
                "dsh_scratch_cwd_failed",
                EXIT_SPAWN_FAILURE,
                outcome="not_started",
                dsh_task_invocations=0,
                error=bounded_text(str(exc)),
            )
        run_cwd = Path(scratch.name)
        command = build_direct_command(dsh_bin, patch_path, prompt)
        completed = run_process(command, run_cwd, runtime_environment(isolated_home))
        stdout, stderr = decode_capture(completed, args.max_capture_bytes)

        if completed.returncode == 0:
            if stderr:
                fail(
                    "dsh_unexpected_stderr",
                    EXIT_INVALID_OUTPUT,
                    outcome="unknown",
                    dsh_task_invocations=1,
                    dsh_stderr=bounded_text(stderr),
                    stdout_bytes=len(stdout.encode("utf-8")),
                    stdout_sha256=sha256_bytes(stdout.encode("utf-8")),
                )
            if not stdout.strip():
                fail(
                    "dsh_empty_result",
                    EXIT_INVALID_OUTPUT,
                    outcome="unknown",
                    dsh_task_invocations=1,
                )
            sys.stdout.write(stdout)
            if not stdout.endswith("\n"):
                sys.stdout.write("\n")
            return 0

        details: dict[str, Any] = {
            "outcome": "unknown",
            "dsh_task_invocations": 1,
            "dsh_exit_code": completed.returncode,
            "stdout_characters": len(stdout),
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        }
        if stderr:
            details["dsh_stderr"] = bounded_text(stderr)
        if stdout.strip():
            # dsh printed assistant text before reporting a non-completed
            # turn: a model task demonstrably started and failed semantically.
            details["outcome"] = "failed"
            details["stdout_excerpt"] = bounded_text(stdout)
            fail("dsh_request_failed", EXIT_SEMANTIC_FAILURE, **details)
        if AUTH_PATTERN.search(stderr):
            details["outcome"] = "failed"
            details["auth_state"] = "unknown"
            details["user_action"] = (
                "Configure the credential referenced by the selected provider "
                "in the dedicated dsh home credential store or host environment, "
                "then confirm before retrying."
            )
            fail("dsh_auth_failed", EXIT_SEMANTIC_FAILURE, **details)
        # dsh has no structured terminal failure event; a boot-time error and a
        # model-task failure can share one shape. Stay conservative: unknown,
        # one possible invocation, and never auto-retry.
        fail("dsh_uncertain_failure", EXIT_SEMANTIC_FAILURE, **details)
    finally:
        if scratch is not None:
            try:
                scratch.cleanup()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
