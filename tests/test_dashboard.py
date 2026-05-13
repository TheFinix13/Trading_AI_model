from fastapi.testclient import TestClient

from agent.dashboard.app import app


def test_health():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_home_renders():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert b"EURUSD" in r.content


def test_kill_resume_cycle(tmp_path, monkeypatch):
    from agent.dashboard import app as dash_module

    fake_ks = tmp_path / "kill_switch"
    monkeypatch.setattr(dash_module.cfg, "kill_switch_file", fake_ks)

    client = TestClient(app)
    r = client.post("/api/kill")
    assert r.json()["kill_active"] is True
    assert fake_ks.exists()
    r = client.post("/api/resume")
    assert r.json()["kill_active"] is False
    assert not fake_ks.exists()
