"""Body config loads the robot-side .env (the daemon launches the app without it)."""

from __future__ import annotations

from soulmount_body.config import load_config


def test_loads_env_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("BRAIN_HOST=10.0.0.9\nBRAIN_PORT=9100\nBRAIN_API_KEY=k9\n")
    monkeypatch.setenv("SOULMOUNT_BODY_ENV", str(tmp_path / ".env"))
    for v in ("BRAIN_HOST", "BRAIN_PORT", "BRAIN_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    cfg = load_config()
    assert cfg.brain_host == "10.0.0.9"
    assert cfg.brain_port == 9100
    assert cfg.brain_api_key == "k9"
    assert cfg.brain_base_url == "http://10.0.0.9:9100"


def test_process_env_overrides_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("BRAIN_HOST=10.0.0.9\n")
    monkeypatch.setenv("SOULMOUNT_BODY_ENV", str(tmp_path / ".env"))
    monkeypatch.setenv("BRAIN_HOST", "192.168.1.5")  # process env wins
    assert load_config().brain_host == "192.168.1.5"
