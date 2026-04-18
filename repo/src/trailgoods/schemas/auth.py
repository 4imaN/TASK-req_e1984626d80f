import re
import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.\-]{3,50}$")
PASSWORD_DIGIT = re.compile(r"\d")
PASSWORD_SYMBOL = re.compile(r"[^a-zA-Z0-9]")


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not USERNAME_PATTERN.match(v):
            raise ValueError(
                "Username must be 3-50 characters: letters, digits, underscore, dot, hyphen"
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if not PASSWORD_DIGIT.search(v):
            raise ValueError("Password must contain at least one digit")
        if not PASSWORD_SYMBOL.search(v):
            raise ValueError("Password must contain at least one symbol")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordRotateRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if not PASSWORD_DIGIT.search(v):
            raise ValueError("Password must contain at least one digit")
        if not PASSWORD_SYMBOL.search(v):
            raise ValueError("Password must contain at least one symbol")
        return v


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionResponse(BaseModel):
    id: uuid.UUID
    status: str
    issued_at: datetime
    last_activity_at: datetime
    ip_address: str | None
    user_agent: str | None

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    token: str
    session: SessionResponse
    user: UserResponse


class IdentityBindingRequest(BaseModel):
    binding_type: str
    institution_code: str
    external_id: str

    @field_validator("institution_code")
    @classmethod
    def validate_institution_code(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9_\-]{2,32}$", v):
            raise ValueError("institution_code must be 2-32 chars: uppercase letters, digits, underscore, hyphen")
        return v

    @field_validator("external_id")
    @classmethod
    def validate_external_id(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 100):
            raise ValueError("external_id must be 1-100 characters")
        return v

    @field_validator("binding_type")
    @classmethod
    def validate_binding_type(cls, v: str) -> str:
        if v not in ("STAFF_ID", "STUDENT_ID"):
            raise ValueError("binding_type must be STAFF_ID or STUDENT_ID")
        return v


class IdentityBindingResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    binding_type: str
    institution_code: str
    external_id: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleAssignRequest(BaseModel):
    user_id: uuid.UUID
    role_name: str


class ForceLogoutRequest(BaseModel):
    user_id: uuid.UUID
    reason: str | None = None
