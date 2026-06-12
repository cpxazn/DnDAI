from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T | None
    error: ErrorDetail | None = None
