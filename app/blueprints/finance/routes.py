from __future__ import annotations

import uuid
from typing import Any

from flask import Blueprint, jsonify, request
from pydantic import BaseModel, ConfigDict

from app.security.session import api_login_required, get_current_user
from app.services import catalog_service, dashboard_service, transaction_service
from app.utils.errors import ApiError
from app.utils.validation import parse_json_body

finance_api_bp = Blueprint("finance_api", __name__, url_prefix="/api/v1")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryCreateBody(_Body):
    name: str
    kind: str


class CatalogUpdateBody(_Body):
    name: str | None = None
    is_archived: bool | None = None


class AccountCreateBody(_Body):
    name: str
    account_type: str
    currency: str | None = None


class TransactionBody(_Body):
    """Values are validated deterministically in transaction_service, not by coercion here."""

    type: Any = None
    amount: Any = None
    currency: Any = None
    transaction_date: Any = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    payment_method: Any = None
    merchant: Any = None
    description: Any = None
    notes: Any = None


def _ok(data=None, status: int = 200, **extra):
    return jsonify({"ok": True, "data": data, **extra}), status


def _archive_scope() -> catalog_service.ArchiveScope:
    """`?archived=only` lists only archived items; `?include_archived=true` lists everything."""
    if request.args.get("archived") == "only":
        return "archived"
    return "all" if request.args.get("include_archived") == "true" else "active"


def _require_update(body: BaseModel) -> None:
    if not body.model_fields_set:
        raise ApiError("Nothing to update.", status_code=400, code="empty_update")



@finance_api_bp.get("/categories")
@api_login_required
def list_categories():
    rows = catalog_service.list_categories(get_current_user(), scope=_archive_scope())
    return _ok({"categories": [r.to_public_dict() for r in rows]})


@finance_api_bp.post("/categories")
@api_login_required
def create_category():
    body = parse_json_body(CategoryCreateBody)
    row = catalog_service.create_category(get_current_user(), name=body.name, kind=body.kind)
    return _ok({"category": row.to_public_dict()}, 201)


@finance_api_bp.patch("/categories/<uuid:category_id>")
@api_login_required
def update_category(category_id: uuid.UUID):
    body = parse_json_body(CatalogUpdateBody)
    _require_update(body)
    row = catalog_service.update_category(get_current_user(), category_id, name=body.name, is_archived=body.is_archived)
    return _ok({"category": row.to_public_dict()})



@finance_api_bp.get("/accounts")
@api_login_required
def list_accounts():
    rows = catalog_service.list_accounts(get_current_user(), scope=_archive_scope())
    return _ok({"accounts": [r.to_public_dict() for r in rows]})


@finance_api_bp.post("/accounts")
@api_login_required
def create_account():
    body = parse_json_body(AccountCreateBody)
    row = catalog_service.create_account(
        get_current_user(), name=body.name, account_type=body.account_type, currency=body.currency
    )
    return _ok({"account": row.to_public_dict()}, 201)


@finance_api_bp.patch("/accounts/<uuid:account_id>")
@api_login_required
def update_account(account_id: uuid.UUID):
    body = parse_json_body(CatalogUpdateBody)
    _require_update(body)
    row = catalog_service.update_account(get_current_user(), account_id, name=body.name, is_archived=body.is_archived)
    return _ok({"account": row.to_public_dict()})



def _warnings(duplicate_ids) -> list[dict]:
    if not duplicate_ids:
        return []
    return [{"code": "possible_duplicate", "transaction_ids": [str(i) for i in duplicate_ids]}]


@finance_api_bp.get("/dashboard")
@api_login_required
def dashboard():
    return _ok(dashboard_service.build_dashboard(get_current_user(), request.args.get("range"), request.args.get("currency")))


@finance_api_bp.get("/transactions")
@api_login_required
def list_transactions():
    return _ok(transaction_service.list_transactions(get_current_user(), request.args))


@finance_api_bp.get("/transactions/summary")
@api_login_required
def transactions_summary():
    return _ok({"totals": transaction_service.summarize(get_current_user(), request.args)})


@finance_api_bp.post("/transactions")
@api_login_required
def create_transaction():
    body = parse_json_body(TransactionBody)
    data = {name: getattr(body, name) for name in TransactionBody.model_fields}
    txn, created, duplicates = transaction_service.create_transaction(
        get_current_user(), data, set(body.model_fields_set), idempotency_key=request.headers.get("Idempotency-Key")
    )
    payload = {"transaction": txn.to_public_dict()}
    if not created:
        return _ok(payload, 200, idempotent_replay=True, warnings=[])
    return _ok(payload, 201, warnings=_warnings(duplicates))


@finance_api_bp.get("/transactions/<uuid:transaction_id>")
@api_login_required
def get_transaction(transaction_id: uuid.UUID):
    return _ok({"transaction": transaction_service.get_transaction(get_current_user(), transaction_id).to_public_dict()})


@finance_api_bp.patch("/transactions/<uuid:transaction_id>")
@api_login_required
def update_transaction(transaction_id: uuid.UUID):
    body = parse_json_body(TransactionBody)
    data = {name: getattr(body, name) for name in TransactionBody.model_fields}
    txn, duplicates = transaction_service.update_transaction(
        get_current_user(), transaction_id, data, set(body.model_fields_set)
    )
    return _ok({"transaction": txn.to_public_dict()}, warnings=_warnings(duplicates))


@finance_api_bp.delete("/transactions/<uuid:transaction_id>")
@api_login_required
def delete_transaction(transaction_id: uuid.UUID):
    transaction_service.delete_transaction(get_current_user(), transaction_id)
    return _ok({"deleted": True})
