from pydantic import BaseModel, EmailStr, validator
from typing import Optional, List
from datetime import datetime


# ─────────────────────────────────────────
# USER SCHEMAS
# ─────────────────────────────────────────

class UserRegister(BaseModel):
    full_name:      str
    email:          EmailStr
    password:       str
    role:           str = "OWNER"   # OWNER | GOVERNMENT | ADMIN
    wallet_address: Optional[str] = None
    phone:          Optional[str] = None

    @validator("role")
    def role_must_be_valid(cls, v):
        allowed = {"OWNER", "GOVERNMENT", "ADMIN"}
        if v.upper() not in allowed:
            raise ValueError(f"Role must be one of {allowed}")
        return v.upper()

    @validator("wallet_address")
    def wallet_must_start_with_0x(cls, v):
        if v is None or v == "":
            return None
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("wallet_address must be a valid Ethereum address (0x...)")
        return v.lower()


class UserLogin(BaseModel):
    email:    EmailStr
    password: str


class UserOut(BaseModel):
    user_id:        int
    full_name:      str
    email:          str
    role:           str
    wallet_address: str
    phone:          Optional[str]
    is_active:      bool
    created_at:     datetime

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user_id:      int
    role:         str
    full_name:    str


# ─────────────────────────────────────────
# PROPERTY SCHEMAS
# ─────────────────────────────────────────

class PropertyRequestCreate(BaseModel):
    property_type: str   # RESIDENTIAL | COMMERCIAL | AGRICULTURAL
    address:       str
    area_sqft:     float
    price:         float
    document_hash: Optional[str] = None

    @validator("price", "area_sqft")
    def must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Must be greater than 0")
        return v

    @validator("property_type")
    def type_must_be_valid(cls, v):
        allowed = {"RESIDENTIAL", "COMMERCIAL", "AGRICULTURAL"}
        if v.upper() not in allowed:
            raise ValueError(f"property_type must be one of {allowed}")
        return v.upper()


class PropertyOut(BaseModel):
    property_id:        int
    registration_number: str
    property_type:      str
    address:            str
    area_sqft:          float
    price:              float
    current_owner_id:   int
    status:             str
    blockchain_tx_hash: Optional[str]
    is_on_chain:        bool
    created_at:         datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# TRANSFER SCHEMAS
# ─────────────────────────────────────────

class TransferRequest(BaseModel):
    property_id:  int
    receiver_id:  int
    amount:       float
    payment_mode: str = "ONLINE"   # ONLINE | CASH | CHEQUE

    @validator("amount")
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v

    @validator("payment_mode")
    def mode_must_be_valid(cls, v):
        allowed = {"ONLINE", "CASH", "CHEQUE"}
        if v.upper() not in allowed:
            raise ValueError(f"payment_mode must be one of {allowed}")
        return v.upper()


class TransactionOut(BaseModel):
    transaction_id:     int
    property_id:        int
    sender_id:          int
    receiver_id:        int
    amount:             float
    payment_mode:       str
    transaction_type:   str
    blockchain_tx_hash: Optional[str]
    is_on_chain:        bool
    timestamp:          datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# DISPUTE SCHEMAS
# ─────────────────────────────────────────

class DisputeRequest(BaseModel):
    property_id: int
    reason:      str


class ResolveDisputeRequest(BaseModel):
    property_id: int


# ─────────────────────────────────────────
# APPROVE / REJECT SCHEMAS
# ─────────────────────────────────────────

class ApproveRequest(BaseModel):
    request_id: int


class RejectRequest(BaseModel):
    request_id: int
    reason:     str


# ─────────────────────────────────────────
# FRAUD SCHEMAS
# ─────────────────────────────────────────

class FraudAlertOut(BaseModel):
    alert_id:        int
    property_id:     Optional[int]
    flagged_user_id: Optional[int]
    transaction_id:  Optional[int]
    fraud_type:      str
    risk_score:      float
    description:     Optional[str]
    is_resolved:     bool
    created_at:      datetime

    class Config:
        from_attributes = True
