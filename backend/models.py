from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    ForeignKey, DateTime, Text
)
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
try:
    from .database import Base
except ImportError:
    from database import Base


# ─────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────

class UserRole(str, enum.Enum):
    OWNER      = "OWNER"
    GOVERNMENT = "GOVERNMENT"
    ADMIN      = "ADMIN"


class PropertyStatus(str, enum.Enum):
    PENDING    = "PENDING"
    REGISTERED = "REGISTERED"
    DISPUTED   = "DISPUTED"
    RESOLVED   = "RESOLVED"
    FROZEN     = "FROZEN"     # owner account deactivated


class TransactionType(str, enum.Enum):
    REGISTER = "REGISTER"
    TRANSFER = "TRANSFER"
    DISPUTE  = "DISPUTE"
    RESOLVE  = "RESOLVE"


class RequestStatus(str, enum.Enum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FraudType(str, enum.Enum):
    AMOUNT_ANOMALY     = "AMOUNT_ANOMALY"
    CIRCULAR_OWNERSHIP = "CIRCULAR_OWNERSHIP"
    RAPID_TRANSFER     = "RAPID_TRANSFER"
    PRICE_MANIPULATION = "PRICE_MANIPULATION"
    SELF_DEALING       = "SELF_DEALING"
    HIGH_FREQ_PAIR     = "HIGH_FREQ_PAIR"
    DUPLICATE_PROPERTY = "DUPLICATE_PROPERTY"


# ─────────────────────────────────────────
# USER
# ─────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    user_id        = Column(Integer, primary_key=True, index=True)
    full_name      = Column(String(200), nullable=False)
    email          = Column(String(200), unique=True, nullable=False, index=True)
    password_hash  = Column(String(300), nullable=False)
    role           = Column(String(20),  nullable=False, default="OWNER")
    wallet_address = Column(String(100), unique=True, nullable=False)
    phone          = Column(String(20))
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    owned_properties = relationship(
        "Property",
        foreign_keys="Property.current_owner_id",
        back_populates="owner"
    )
    sent_transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.sender_id",
        back_populates="sender"
    )
    received_transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.receiver_id",
        back_populates="receiver"
    )
    property_requests = relationship(
        "PropertyRequest",
        back_populates="owner"
    )
    # Only link to fraud alerts where this user is the FLAGGED user
    fraud_alerts = relationship(
        "FraudAlert",
        foreign_keys="FraudAlert.flagged_user_id",
        back_populates="flagged_user"
    )


# ─────────────────────────────────────────
# PROPERTY
# ─────────────────────────────────────────

class Property(Base):
    __tablename__ = "properties"

    property_id         = Column(Integer, primary_key=True, index=True)
    registration_number = Column(String(50),  unique=True, nullable=False, index=True)
    property_type       = Column(String(50),  nullable=False)
    address             = Column(Text,        nullable=False)
    area_sqft           = Column(Float,       nullable=False)
    price               = Column(Float,       nullable=False)
    current_owner_id    = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    status              = Column(String(20),  default="PENDING")
    blockchain_tx_hash  = Column(String(200))
    is_on_chain         = Column(Boolean, default=False)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    owner        = relationship("User",        foreign_keys=[current_owner_id], back_populates="owned_properties")
    transactions = relationship("Transaction", back_populates="property")
    fraud_alerts = relationship("FraudAlert",  foreign_keys="FraudAlert.property_id", back_populates="property")


# ─────────────────────────────────────────
# PROPERTY REQUEST
# ─────────────────────────────────────────

class PropertyRequest(Base):
    __tablename__ = "property_requests"

    request_id    = Column(Integer, primary_key=True, index=True)
    owner_id      = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    property_type = Column(String(50), nullable=False)
    address       = Column(Text,       nullable=False)
    area_sqft     = Column(Float,      nullable=False)
    price         = Column(Float,      nullable=False)
    document_hash = Column(String(200))
    status        = Column(String(20), default="PENDING")
    reject_reason = Column(Text)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="property_requests")


# ─────────────────────────────────────────
# TRANSACTION
# ─────────────────────────────────────────

class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id     = Column(Integer, primary_key=True, index=True)
    property_id        = Column(Integer, ForeignKey("properties.property_id"), nullable=False)
    sender_id          = Column(Integer, ForeignKey("users.user_id"),          nullable=False)
    receiver_id        = Column(Integer, ForeignKey("users.user_id"),          nullable=False)
    amount             = Column(Float,      nullable=False)
    payment_mode       = Column(String(30), default="ONLINE")
    transaction_type   = Column(String(20), default="TRANSFER")
    blockchain_tx_hash = Column(String(200))
    is_on_chain        = Column(Boolean, default=False)
    timestamp          = Column(DateTime, default=datetime.utcnow, index=True)

    # relationships
    property    = relationship("Property",    back_populates="transactions")
    sender      = relationship("User", foreign_keys=[sender_id],   back_populates="sent_transactions")
    receiver    = relationship("User", foreign_keys=[receiver_id], back_populates="received_transactions")
    fraud_alert = relationship("FraudAlert",  foreign_keys="FraudAlert.transaction_id", back_populates="transaction", uselist=False)


# ─────────────────────────────────────────
# ACTIVITY LOG (tracks government actions)
# ─────────────────────────────────────────

class ActivityLog(Base):
    __tablename__ = "activity_logs"

    log_id       = Column(Integer, primary_key=True, index=True)
    actor_id     = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    action       = Column(String(50),  nullable=False)   # APPROVE / REJECT / DISPUTE / RESOLVE / DEACTIVATE / CREATE_USER
    target_type  = Column(String(30),  nullable=False)   # PROPERTY / USER / REQUEST / DISPUTE
    target_id    = Column(Integer,     nullable=True)    # ID of the affected object
    details      = Column(Text,        nullable=True)    # extra info
    created_at   = Column(DateTime, default=datetime.utcnow, index=True)

    actor = relationship("User", foreign_keys=[actor_id])


# ─────────────────────────────────────────
# FRAUD ALERT
# ─────────────────────────────────────────

class FraudAlert(Base):
    __tablename__ = "fraud_alerts"

    alert_id        = Column(Integer, primary_key=True, index=True)
    property_id     = Column(Integer, ForeignKey("properties.property_id"),    nullable=True)
    flagged_user_id = Column(Integer, ForeignKey("users.user_id"),             nullable=True)
    transaction_id  = Column(Integer, ForeignKey("transactions.transaction_id"), nullable=True)
    fraud_type      = Column(String(30), nullable=False)
    risk_score      = Column(Float,      nullable=False)
    description     = Column(Text)
    is_resolved     = Column(Boolean, default=False)
    resolved_by     = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    resolved_at     = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    # relationships — all foreign_keys explicitly specified to avoid ambiguity
    property     = relationship("Property",    foreign_keys=[property_id],     back_populates="fraud_alerts")
    flagged_user = relationship("User",        foreign_keys=[flagged_user_id], back_populates="fraud_alerts")
    transaction  = relationship("Transaction", foreign_keys=[transaction_id],  back_populates="fraud_alert")
