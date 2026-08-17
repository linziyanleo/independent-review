from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


class PiAdapterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
