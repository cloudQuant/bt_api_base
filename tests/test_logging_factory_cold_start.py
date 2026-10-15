"""Cold-start tests for the default stdlib logging path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_default_logger_cold_start_uses_stdlib_without_spdlog_import(tmp_path) -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    env["BT_API_LOG_DIR"] = str(tmp_path)
    program = r"""
import json
import logging
import sys

spdlog_imports = []
spdlog_probes = []

class SpdlogProbeRecorder:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "spdlog" or fullname.startswith("spdlog."):
            spdlog_probes.append(fullname)
        return None

sys.meta_path.insert(0, SpdlogProbeRecorder())

def record_import(event, args):
    if event == "import" and args and isinstance(args[0], str):
        if args[0] == "spdlog" or args[0].startswith("spdlog."):
            spdlog_imports.append(args[0])

sys.addaudithook(record_import)
from bt_api_base.logging_factory import get_logger

logger = get_logger("cold-start-default")
logger.info("cold-start %s", "ready")
for handler in logger._logger.handlers:
    handler.flush()
print(json.dumps({
    "logger_is_stdlib": isinstance(logger._logger, logging.Logger),
    "spdlog_imports": spdlog_imports,
    "spdlog_probes": spdlog_probes,
    "spdlog_loaded": "spdlog" in sys.modules,
}))
"""

    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        "logger_is_stdlib": True,
        "spdlog_imports": [],
        "spdlog_probes": [],
        "spdlog_loaded": False,
    }
    assert "cold-start ready" in (tmp_path / "cold-start-default.log").read_text(
        encoding="utf-8"
    )
