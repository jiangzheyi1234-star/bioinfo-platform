from __future__ import annotations

from typing import Any


def data_response(value: Any) -> dict[str, Any]:
    return {"data": value}


def item_response(value: Any) -> dict[str, Any]:
    return {"item": value}


def items_response(value: Any) -> dict[str, Any]:
    return {"items": value}


def wrapped_response(value: Any, *, wrapper: str = "raw") -> Any:
    if wrapper == "raw":
        return value
    if wrapper == "item":
        return item_response(value)
    if wrapper == "data":
        return data_response(value)
    if wrapper == "items":
        return items_response(value)
    if wrapper == "data_items":
        return data_response(items_response(value))
    raise ValueError(f"Unsupported runtime wrapper: {wrapper}")
