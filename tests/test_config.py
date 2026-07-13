import json

from core.config import CONFIG_SCHEMA_VERSION, ConfigManager


def test_config_roundtrip_persists_api_keys(tmp_path):
    path = tmp_path / "config.json"
    manager = ConfigManager(path)
    manager.config.groq_api_key = "groq-secret"
    manager.config.xunfei_api_key = "xunfei-secret"
    manager.config.music_dirs = ["D:/Music"]

    manager.save()
    loaded = ConfigManager(path).load()

    assert loaded.groq_api_key == "groq-secret"
    assert loaded.xunfei_api_key == "xunfei-secret"
    assert loaded.music_dirs == ["D:/Music"]

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == CONFIG_SCHEMA_VERSION


def test_environment_api_key_takes_precedence(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"groq_api_key": "file-secret", "xunfei_api_key": "file-xunfei"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GROQ_API_KEY", "environment-secret")
    monkeypatch.setenv("XUNFEI_API_KEY", "environment-xunfei")

    loaded = ConfigManager(path).load()

    assert loaded.groq_api_key == "environment-secret"
    assert loaded.xunfei_api_key == "environment-xunfei"
