from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_legacy_gateway_import_is_lazy_and_explicit_use_names_extra() -> None:
    source_root = Path(__file__).parents[2] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(source_root), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    script = r"""
import importlib.abc
import importlib
import json
import sys

class RejectZmq(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "zmq" or fullname.startswith("zmq."):
            raise ModuleNotFoundError("No module named 'zmq'", name="zmq")
        return None

sys.meta_path.insert(0, RejectZmq())
import bt_api_base
from bt_api_base.gateway.config import GatewayConfig
runtime_module = importlib.import_module("bt_api_base.gateway.runtime_remote")
assert not any(name == "zmq" or name.startswith("zmq.") for name in sys.modules)

try:
    runtime_module.GatewayRuntime(GatewayConfig())
except ImportError as exc:
    message = str(exc)
    assert "bt_api_base[transport-zmq]" in message
    assert "bt_api_py[transport-zmq]" in message
else:
    raise AssertionError("explicit remote runtime use must require its ZMQ extra")

assert not any(name == "zmq" or name.startswith("zmq.") for name in sys.modules)
print(json.dumps({"lazy_import": True, "explicit_extra_error": message}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    outcome = json.loads(result.stdout)
    assert outcome["lazy_import"] is True
    assert "bt_api_base[transport-zmq]" in outcome["explicit_extra_error"]
