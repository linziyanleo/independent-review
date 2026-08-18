from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
QODER_PATH = ROOT / "scripts" / "adapters" / "qodercli-task.py"
PI_PATH = ROOT / "scripts" / "adapters" / "pi-agent-task.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


QODER = load_module("independent_review_qoder_adapter", QODER_PATH)
PI = load_module("independent_review_pi_adapter", PI_PATH)


class QoderAdapterTests(unittest.TestCase):
    def test_prompt_argv_is_read_only_stateless_and_zero_retry(self):
        args = argparse.Namespace(
            model="ultimate",
            agent="general-purpose",
            max_output_tokens=4096,
            reasoning_effort="high",
            tools="Read,Grep,Glob",
        )
        command = QODER.build_command("/bin/qodercli", args, Path("/repo"), "prompt")
        self.assertIn("dont_ask", command)
        self.assertIn("--no-session-persistence", command)
        self.assertEqual(command[command.index("--max-model-request-retries") + 1], "0")
        self.assertEqual(command[command.index("--allowed-tools") + 1], "Read,Grep,Glob")
        self.assertEqual(command[-2:], ["--", "prompt"])

    def test_preflight_error_is_standard_json_envelope(self):
        completed = subprocess.run(
            [sys.executable, str(QODER_PATH), "prompt"],
            capture_output=True,
            text=True,
            check=False,
        )
        diagnostic = json.loads(completed.stderr)
        self.assertEqual(diagnostic["type"], "independent_review_adapter_diagnostic")
        self.assertEqual(diagnostic["outcome"], "not_started")
        self.assertEqual(diagnostic["backend_task_invocations"], 0)
        self.assertIsInstance(diagnostic["details"], dict)

    def test_prompt_size_guard_lives_in_adapter(self):
        self.assertGreaterEqual(QODER.half_arg_max_limit(), 65_536)

    def test_login_shell_capture_lives_in_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            zsh = Path(directory) / "zsh"
            zsh.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "sys.stdout.buffer.write(b'QODER_TEST=from-zshrc\\0PATH=/usr/bin\\0')\n",
                encoding="utf-8",
            )
            zsh.chmod(0o755)
            environment = QODER.login_zsh_environment(
                {"PATH": directory + os.pathsep + os.environ.get("PATH", "")}
            )
        self.assertEqual(environment["QODER_TEST"], "from-zshrc")

    def test_explicit_binary_survives_login_shell_path_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "selected" / "qodercli"
            selected.parent.mkdir()
            selected.write_text("#!/bin/sh\n", encoding="utf-8")
            selected.chmod(0o755)
            ambient = root / "ambient" / "qodercli"
            ambient.parent.mkdir()
            ambient.write_text("#!/bin/sh\n", encoding="utf-8")
            ambient.chmod(0o755)
            prompt = root / "prompt.md"
            prompt.write_text("Review this change.\n", encoding="utf-8")
            captured_command = []

            def fake_run_process(command, cwd, timeout_seconds, env):
                captured_command.extend(command)
                envelope = {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "Verdict: approve\n",
                    "permission_denials": [],
                }
                return subprocess.CompletedProcess(
                    command, 0, stdout=json.dumps(envelope).encode("utf-8"), stderr=b""
                )

            argv = [
                str(QODER_PATH),
                "prompt",
                "--cwd",
                str(root),
                "--prompt-file",
                str(prompt),
                "--qodercli-bin",
                str(selected),
            ]
            login_env = {"PATH": str(ambient.parent)}
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(QODER, "login_zsh_environment", return_value=login_env),
                mock.patch.object(QODER, "run_process", side_effect=fake_run_process),
                mock.patch.object(sys, "stdout", io.StringIO()),
            ):
                self.assertEqual(QODER.main(), 0)

        self.assertEqual(captured_command[0], str(selected))


class PiAdapterTests(unittest.TestCase):
    def tearDown(self):
        PI._ACTIVE_RECEIPT = None

    def test_provider_model_pairing_failure_is_standard_json_envelope(self):
        completed = subprocess.run(
            [sys.executable, str(PI_PATH), "prompt", "--provider", "vendor"],
            capture_output=True,
            text=True,
            check=False,
        )
        diagnostic = json.loads(completed.stderr)
        self.assertEqual(diagnostic["type"], "independent_review_adapter_diagnostic")
        self.assertEqual(diagnostic["kind"], "invalid_arguments")
        self.assertEqual(diagnostic["outcome"], "not_started")
        self.assertEqual(diagnostic["backend_task_invocations"], 0)

    def test_removed_second_prompt_surface_is_rejected_before_invocation(self):
        completed = subprocess.run(
            [sys.executable, str(PI_PATH), "propose-patch"],
            capture_output=True,
            text=True,
            check=False,
        )
        diagnostic = json.loads(completed.stderr)
        self.assertEqual(diagnostic["kind"], "invalid_arguments")
        self.assertEqual(diagnostic["backend_task_invocations"], 0)

    def test_explicit_pi_and_node_binaries_drive_sdk_and_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected_pi = root / "selected" / "pi"
            selected_node = root / "selected" / "node"
            selected_pi.parent.mkdir()
            for binary in (selected_pi, selected_node):
                binary.write_text("#!/bin/sh\n", encoding="utf-8")
                binary.chmod(0o755)
            package_dir = root / "pi-package"
            (package_dir / "dist").mkdir(parents=True)
            (package_dir / "package.json").write_text(
                json.dumps({"name": "@earendil-works/pi-coding-agent"}),
                encoding="utf-8",
            )
            (package_dir / "dist" / "index.js").write_text("", encoding="utf-8")
            prompt = root / "prompt.md"
            prompt.write_text("Review this change.\n", encoding="utf-8")
            observed = {}

            def fake_run_bridge(node_bin, bridge, cwd, request, timeout_policy):
                observed["node_bin"] = node_bin
                payload = json.loads(request)
                observed["package_dir"] = payload["package_dir"]
                envelope = {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "invocation_id": payload["invocation_id"],
                    "pi_session_id": payload["pi_session_id"],
                    "provider": "fake-provider",
                    "model": "fake-model",
                    "thinking_level": "medium",
                    "pi_task_invocations": 1,
                    "provider_request_count": 1,
                    "retry_events": 0,
                    "agent_start_events": 1,
                    "agent_end_events": 1,
                    "stop_reason": "stop",
                    "tool_events": [],
                    "result": "Verdict: approve\n",
                }
                return 0, (json.dumps(envelope) + "\n").encode("utf-8"), b""

            argv = [
                str(PI_PATH),
                "prompt",
                "--cwd",
                str(root),
                "--prompt-file",
                str(prompt),
                "--package-dir",
                str(package_dir),
                "--receipt-dir",
                str(root / "receipts"),
                "--pi-bin",
                str(selected_pi),
                "--node-bin",
                str(selected_node),
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(PI, "run_bridge", side_effect=fake_run_bridge),
                mock.patch.object(sys, "stdout", io.StringIO()),
            ):
                self.assertEqual(PI.main(), 0)

        self.assertEqual(observed["node_bin"], str(selected_node))
        self.assertEqual(observed["package_dir"], str(package_dir.resolve()))



if __name__ == "__main__":
    unittest.main()
