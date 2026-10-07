import pytest

from megooarti import __main__ as launcher


def test_launcher_serves_the_app_factory_with_values_from_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", "postgresql://u:p@db:5432/m")
    monkeypatch.setenv("MEGOOARTI_PORT", "9001")
    monkeypatch.setenv("MEGOOARTI_SHUTDOWN_GRACE_SECONDS", "7")
    monkeypatch.setenv("MEGOOARTI_FORWARDED_ALLOW_IPS", "10.0.0.1")
    monkeypatch.setenv("MEGOOARTI_LOG_LEVEL", "warning")
    monkeypatch.chdir(tmp_path)
    calls, levels = [], []
    monkeypatch.setattr(
        launcher.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setattr(launcher, "configure_logging", levels.append)

    launcher.main()

    assert levels == ["WARNING"]
    ((args, kwargs),) = calls
    assert args == ("megooarti.main:create_app",)
    assert kwargs == {
        "factory": True,
        "host": "0.0.0.0",
        "port": 9001,
        "proxy_headers": True,
        "forwarded_allow_ips": "10.0.0.1",
        "timeout_graceful_shutdown": 7,
        "log_config": None,
    }


def test_launcher_reports_missing_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("MEGOOARTI_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        launcher.main()

    assert "MEGOOARTI_DATABASE_URL" in str(stopped.value)
