from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int


class ResponseMeta(BaseModel):
    request_id: str
    pagination: PaginationMeta | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiResponse(BaseModel, Generic[T]):
    data: T | None = None
    meta: ResponseMeta
    error: ErrorDetail | None = None
