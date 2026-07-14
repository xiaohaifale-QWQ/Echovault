import sys
from pathlib import Path

import pytest

from core.asr.worker_client import WorkerClient, WorkerRemoteError


def _worker_client() -> WorkerClient:
    project_root = Path(__file__).resolve().parents[1]
    return WorkerClient([sys.executable, "-m", "worker.asr_worker"], cwd=str(project_root))


def test_worker_client_ping_doctor_and_shutdown():
    client = _worker_client()
    try:
        ping = client.request("ping")
        report = client.request("doctor")
    finally:
        client.close()

    assert ping["worker_version"] == "0.1.0"
    assert report["protocol_version"] == 1
    assert report["device"] in {"cpu", "cuda"}


def test_worker_client_exposes_structured_remote_errors():
    client = _worker_client()
    try:
        with pytest.raises(WorkerRemoteError) as exc_info:
            client.request("unsupported")
    finally:
        client.close()

    assert exc_info.value.code == "UNKNOWN_ACTION"
