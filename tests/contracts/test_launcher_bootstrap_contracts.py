import pytest

from launcher_support import bootstrap


def test_load_vps_config_uses_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "VPS_CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(bootstrap, "_VPS_CFG_CACHE", {"mtime": None, "value": None})
    cfg = bootstrap.load_vps_config()
    assert cfg["host"] == ""
    assert cfg["host_display"] == "UNCONFIGURED"
    assert cfg["remote_dir"] == bootstrap.VPS_PROJECT


def test_load_vps_config_reads_frontend_backend_shared_file(tmp_path, monkeypatch):
    path = tmp_path / "vps.json"
    path.write_text(
        '{"host":"10.0.0.9","port":"2222","user":"aurum","key_path":"C:/keys/id_ed25519","remote_dir":"/srv/aurum"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "VPS_CONFIG_PATH", path)
    monkeypatch.setattr(bootstrap, "_VPS_CFG_CACHE", {"mtime": None, "value": None})
    cfg = bootstrap.load_vps_config()
    assert cfg["host_display"] == "aurum@10.0.0.9"
    assert cfg["port"] == "2222"
    assert cfg["key_path"] == "C:/keys/id_ed25519"
    assert cfg["remote_dir"] == "/srv/aurum"


def test_load_vps_config_normalizes_legacy_user_at_host(tmp_path, monkeypatch):
    path = tmp_path / "vps.json"
    path.write_text(
        '{"host":"root@10.0.0.9","port":"2222","key_path":"C:/keys/id_ed25519","remote_dir":"/srv/aurum"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "VPS_CONFIG_PATH", path)
    monkeypatch.setattr(bootstrap, "_VPS_CFG_CACHE", {"mtime": None, "value": None})
    cfg = bootstrap.load_vps_config()
    assert cfg["host"] == "10.0.0.9"
    assert cfg["user"] == "root"
    assert cfg["host_display"] == "root@10.0.0.9"


def test_build_vps_ssh_command_honors_port_and_key(tmp_path, monkeypatch):
    path = tmp_path / "vps.json"
    path.write_text(
        '{"host":"10.0.0.9","port":"2222","user":"aurum","key_path":"C:/keys/id_ed25519","remote_dir":"/srv/aurum"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "VPS_CONFIG_PATH", path)
    monkeypatch.setattr(bootstrap, "_VPS_CFG_CACHE", {"mtime": None, "value": None})
    cmd = bootstrap.build_vps_ssh_command("echo ok")
    assert cmd[-2:] == ["aurum@10.0.0.9", "echo ok"]
    assert "-p" in cmd and "2222" in cmd
    assert "-i" in cmd and "C:/keys/id_ed25519" in cmd


def test_build_vps_ssh_command_accepts_legacy_user_at_host(tmp_path, monkeypatch):
    path = tmp_path / "vps.json"
    path.write_text(
        '{"host":"root@10.0.0.9","port":"2222","key_path":"C:/keys/id_ed25519","remote_dir":"/srv/aurum"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "VPS_CONFIG_PATH", path)
    monkeypatch.setattr(bootstrap, "_VPS_CFG_CACHE", {"mtime": None, "value": None})
    cmd = bootstrap.build_vps_ssh_command("echo ok")
    assert cmd[-2:] == ["root@10.0.0.9", "echo ok"]


def test_build_vps_ssh_command_requires_explicit_host(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "VPS_CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(bootstrap, "_VPS_CFG_CACHE", {"mtime": None, "value": None})
    with pytest.raises(ValueError, match="not configured"):
        bootstrap.build_vps_ssh_command("echo ok")


def test_build_millennium_bootstrap_launch_command_targets_dedicated_session():
    cmd = bootstrap.build_millennium_bootstrap_launch_command("/srv/aurum", mode="diag")
    assert bootstrap.VPS_MILLENNIUM_SCREEN in cmd
    assert "python3 -m engines.millennium_live diag" in cmd
    assert "bootstrap.latest.log" in cmd


def test_build_vps_stop_command_covers_live_and_millennium_sessions():
    cmd = bootstrap.build_vps_stop_command()
    assert bootstrap.VPS_LIVE_SCREEN in cmd
    assert bootstrap.VPS_MILLENNIUM_SCREEN in cmd


def test_build_vps_log_tail_command_includes_bootstrap_log():
    cmd = bootstrap.build_vps_log_tail_command("/srv/aurum")
    assert "/srv/aurum/data/live/*/logs/live.log" in cmd
    assert "/srv/aurum/data/millennium_live/bootstrap.latest.log" in cmd
