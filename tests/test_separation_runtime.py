import json

from core import separation_runtime


def test_active_separation_gpu_runtime_reuses_cuda_worker_torch(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtimes" / "cuda-test"
    worker_dir = runtime_dir / "worker"
    (worker_dir / "_internal" / "torch").mkdir(parents=True)
    worker = worker_dir / "echovault-asr-worker.exe"
    worker.write_bytes(b"worker")
    (runtime_dir / "runtime.json").write_text(
        json.dumps({"runtime_id": "cuda-test", "backend": "cuda"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        separation_runtime, "active_worker_command", lambda: [str(worker)]
    )

    selected = separation_runtime.active_separation_gpu_runtime()

    assert selected is not None
    assert selected.runtime_id == "cuda-test"
    assert selected.internal_path == worker_dir / "_internal"
    assert separation_runtime.separation_gpu_available()


def test_active_separation_gpu_runtime_rejects_cpu_worker(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtimes" / "cpu-test"
    worker_dir = runtime_dir / "worker"
    (worker_dir / "_internal" / "torch").mkdir(parents=True)
    worker = worker_dir / "worker.exe"
    worker.write_bytes(b"worker")
    (runtime_dir / "runtime.json").write_text(
        json.dumps({"runtime_id": "cpu-test", "backend": "cpu"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        separation_runtime, "active_worker_command", lambda: [str(worker)]
    )

    assert separation_runtime.active_separation_gpu_runtime() is None
