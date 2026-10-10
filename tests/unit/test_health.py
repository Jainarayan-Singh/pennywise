from unittest.mock import patch


def test_app_starts_and_liveness_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "alive"
    assert res.headers["X-Request-ID"]
    assert res.headers["X-Content-Type-Options"] == "nosniff"


def test_readiness_reports_database_up(client):
    res = client.get("/health/ready")
    assert res.status_code == 200
    assert res.get_json()["database"] == "up"


def test_readiness_degrades_without_leaking_details(client):
    from sqlalchemy.exc import OperationalError

    boom = OperationalError("SELECT 1", {}, Exception("secret-dsn"))
    with patch("app.services.database_check.db.session.execute", side_effect=boom):
        res = client.get("/health/ready")
    assert res.status_code == 503
    assert "secret-dsn" not in res.get_data(as_text=True)
    assert res.get_json()["database"] == "down"


def test_unknown_api_route_returns_json_error(client):
    res = client.get("/api/v1/nope")
    assert res.status_code == 404
    assert res.get_json() == {"ok": False, "error": {"code": "not_found", "message": "Not Found"}}


def test_request_id_echoed_when_valid(client):
    res = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert res.headers["X-Request-ID"] == "abc123"
