from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_remote_runtime_migrates_before_optional_zmq_load_and_proxy_names_extra() -> None:
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
from bt_api_base.exceptions import ConfigurationError
from bt_api_base.gateway.config import GatewayConfig
runtime_module = importlib.import_module("bt_api_base.gateway.runtime_remote")
assert not any(name == "zmq" or name.startswith("zmq.") for name in sys.modules)

class ManualAdapter:
    pass

runtime_module.GatewayRuntime.register_adapter("CTP", ManualAdapter)
try:
    runtime_module.GatewayRuntime(GatewayConfig())
except ConfigurationError as exc:
    migration_message = str(exc)
    assert "ServiceHost" in migration_message
    assert "service.order_entry" in migration_message
else:
    raise AssertionError("legacy remote runtime must require migration")

assert not any(name == "zmq" or name.startswith("zmq.") for name in sys.modules)

try:
    runtime_module.zmq.Context
except ImportError as exc:
    extra_message = str(exc)
    assert "bt_api_base[transport-zmq]" in extra_message
    assert "bt_api_py[transport-zmq]" in extra_message
else:
    raise AssertionError("direct optional transport use must require its ZMQ extra")

assert not any(name == "zmq" or name.startswith("zmq.") for name in sys.modules)
print(json.dumps({
    "migration_error": migration_message,
    "explicit_extra_error": extra_message,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    outcome = json.loads(result.stdout)
    assert "ServiceHost" in outcome["migration_error"]
    assert "service.order_entry" in outcome["migration_error"]
    assert "bt_api_base[transport-zmq]" in outcome["explicit_extra_error"]
