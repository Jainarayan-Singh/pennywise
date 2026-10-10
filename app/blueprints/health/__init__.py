from flask import Blueprint, current_app, jsonify

from app.services.database_check import check_database

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def liveness():
    """Process is up. Never touches external services."""
    return jsonify({"ok": True, "status": "alive", "app": current_app.extensions["settings"].app.name})


@health_bp.get("/health/ready")
def readiness():
    """Database reachability. Returns 503 without leaking error details."""
    result = check_database()
    if result["connected"]:
        return jsonify({"ok": True, "status": "ready", "database": "up"})
    body = {"ok": False, "status": "degraded", "database": "down"}
    if current_app.extensions["settings"].app.env != "production":
        body["reason"] = result["reason"]  # diagnostics only outside production
    return jsonify(body), 503
