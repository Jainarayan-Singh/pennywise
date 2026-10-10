"""Request-body validation with pydantic; never echoes submitted values back."""
from __future__ import annotations

from typing import TypeVar

from flask import request
from pydantic import BaseModel, ValidationError

from app.utils.errors import ApiError, ValidationFailed

ModelT = TypeVar("ModelT", bound=BaseModel)


def parse_json_body(model: type[ModelT]) -> ModelT:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("Request body must be a JSON object.", status_code=400, code="invalid_json")
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        fields = {
            ".".join(str(p) for p in err["loc"]) or "body": err["msg"]
            for err in exc.errors(include_input=False, include_url=False, include_context=False)
        }
        raise ValidationFailed("Some fields are invalid.", details=fields) from None
