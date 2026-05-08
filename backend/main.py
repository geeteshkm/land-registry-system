"""
Blockchain Land Registry System — Backend API
==============================================
FastAPI + PostgreSQL + Web3 (Sepolia)
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, aliased
from datetime import datetime
from pathlib import Path
from eth_account import Account
import hashlib
import json
import re
import time

try:
    from .database import engine, Base, get_db
    from . import models
    from . import schemas
    from .auth import (
        hash_password, verify_password, create_access_token,
        get_current_user, require_role,
    )
    from .blockchain_connector import (
        CONTRACT_ADDRESS,
        get_property_audit_trail_from_chain,
        register_property_on_chain,
        transfer_property_on_chain,
        raise_dispute_on_chain,
        resolve_dispute_on_chain,
        get_property_details_from_chain,
        get_property_owner_from_chain,
        get_property_history_from_chain,
        verify_property_on_chain,
        get_chain_stats,
    )
    from .fraud_detection import run_fraud_analysis
except ImportError:
    from database import engine, Base, get_db
    import models
    import schemas
    from auth import (
        hash_password, verify_password, create_access_token,
        get_current_user, require_role,
    )
    from blockchain_connector import (
        CONTRACT_ADDRESS,
        get_property_audit_trail_from_chain,
        register_property_on_chain,
        transfer_property_on_chain,
        raise_dispute_on_chain,
        resolve_dispute_on_chain,
        get_property_details_from_chain,
        get_property_owner_from_chain,
        get_property_history_from_chain,
        verify_property_on_chain,
        get_chain_stats,
    )
    from fraud_detection import run_fraud_analysis

# ─────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Blockchain Land Registry API",
    version="2.0.0",
    description="Secure land registry with blockchain verification and AI fraud detection",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def generate_registration_number(db: Session) -> str:
    count = db.query(models.Property).count()
    return f"REG{datetime.utcnow().year}{str(count + 1).zfill(5)}"


def generate_tx_hash(data: str) -> str:
    return hashlib.sha256(f"{data}{time.time()}".encode()).hexdigest()


def build_property_state_hash(prop: models.Property) -> str:
    payload = "|".join([
        str(prop.property_id),
        prop.registration_number or "",
        prop.address or "",
        str(prop.current_owner_id),
        str(int(prop.price or 0)),
        prop.status or "",
    ])
    return hashlib.sha256(payload.encode()).hexdigest()


def normalize_address_text(address: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (address or "").strip().lower())


def compute_property_fingerprint(property_type: str, address: str, area_sqft: float) -> str:
    payload = "|".join([
        (property_type or "").strip().upper(),
        normalize_address_text(address),
        f"{float(area_sqft):.2f}",
    ])
    return hashlib.sha256(payload.encode()).hexdigest()


def find_duplicate_records(
    db: Session,
    property_type: str,
    address: str,
    area_sqft: float,
    exclude_request_id: int | None = None,
) -> dict:
    fingerprint = compute_property_fingerprint(property_type, address, area_sqft)

    matched_properties = []
    for prop in db.query(models.Property).all():
        if compute_property_fingerprint(prop.property_type, prop.address, prop.area_sqft) == fingerprint:
            matched_properties.append(prop)

    request_query = db.query(models.PropertyRequest).filter(
        models.PropertyRequest.status.in_(["PENDING", "APPROVED"])
    )
    if exclude_request_id is not None:
        request_query = request_query.filter(models.PropertyRequest.request_id != exclude_request_id)

    matched_requests = []
    for req in request_query.all():
        if compute_property_fingerprint(req.property_type, req.address, req.area_sqft) == fingerprint:
            matched_requests.append(req)

    return {
        "fingerprint": fingerprint,
        "properties": matched_properties,
        "requests": matched_requests,
    }


def create_fraud_alert(
    db: Session,
    fraud_type: str,
    description: str,
    risk_score: float,
    property_id: int | None = None,
    flagged_user_id: int | None = None,
    transaction_id: int | None = None,
):
    existing = db.query(models.FraudAlert).filter(
        models.FraudAlert.fraud_type == fraud_type,
        models.FraudAlert.property_id == property_id,
        models.FraudAlert.flagged_user_id == flagged_user_id,
        models.FraudAlert.is_resolved == False,
    ).first()
    if existing and existing.description == description:
        return existing

    alert = models.FraudAlert(
        property_id=property_id,
        flagged_user_id=flagged_user_id,
        transaction_id=transaction_id,
        fraud_type=fraud_type,
        risk_score=risk_score,
        description=description,
    )
    db.add(alert)
    return alert


def generate_unique_wallet_address(db: Session) -> str:
    while True:
        wallet_address = Account.create().address.lower()
        exists = db.query(models.User).filter(
            models.User.wallet_address == wallet_address
        ).first()
        if not exists:
            return wallet_address


def load_evaluation_metrics() -> dict:
    summary_path = Path(__file__).resolve().parent / "artifacts" / "fraud_evaluation_summary.json"
    if not summary_path.exists():
        return {
            "available": False,
            "message": "Evaluation summary not found. Run evaluate_fraud_dataset.py to generate metrics.",
        }

    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        overall = data.get("rule_engine", {}).get("overall", {})
        return {
            "available": True,
            "precision": overall.get("precision"),
            "recall": overall.get("recall"),
            "f1": overall.get("f1"),
            "auc": overall.get("auc"),
        }
    except Exception as e:
        return {
            "available": False,
            "message": f"Failed to read evaluation summary: {e}",
        }


def risk_bucket(score: float | None) -> str:
    value = float(score or 0)
    if value >= 70:
        return "High"
    if value >= 40:
        return "Medium"
    return "Low"


# ─────────────────────────────────────────
# ROOT
# ─────────────────────────────────────────

@app.get("/")
def root():
    return {
        "status":  "Blockchain Land Registry API is running",
        "version": "2.0.0",
        "docs":    "/docs",
    }


# ═══════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════

@app.post("/users/register", response_model=schemas.UserOut, tags=["Auth"])
def register_user(payload: schemas.UserRegister, db: Session = Depends(get_db)):
    """Register a new user (Owner / Government / Admin)."""

    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    wallet_address = (payload.wallet_address or "").lower() or generate_unique_wallet_address(db)

    if db.query(models.User).filter(
        models.User.wallet_address == wallet_address
    ).first():
        raise HTTPException(status_code=400, detail="Wallet address already registered")

    user = models.User(
        full_name      = payload.full_name,
        email          = payload.email,
        password_hash  = hash_password(payload.password),
        role           = payload.role.upper(),
        wallet_address = wallet_address,
        phone          = payload.phone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/users/login", response_model=schemas.TokenOut, tags=["Auth"])
def login(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    """Login and receive JWT token."""

    user = db.query(models.User).filter(models.User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    token = create_access_token({"user_id": user.user_id, "role": user.role})

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      user.user_id,
        "role":         user.role,
        "full_name":    user.full_name,
    }


@app.get("/users/me", response_model=schemas.UserOut, tags=["Auth"])
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user


# ─────────────────────────────────────────
# HELPER — LOG ACTIVITY
# ─────────────────────────────────────────

def log_activity(
    db:          Session,
    actor_id:    int,
    action:      str,
    target_type: str,
    target_id:   int  = None,
    details:     str  = None,
):
    entry = models.ActivityLog(
        actor_id    = actor_id,
        action      = action,
        target_type = target_type,
        target_id   = target_id,
        details     = details,
    )
    db.add(entry)
    db.commit()


# ═══════════════════════════════════════════
# USER MANAGEMENT (Admin only)
# ═══════════════════════════════════════════

@app.get("/users", tags=["Admin"])
def list_users(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role("ADMIN")),
):
    """Admin views all users across all roles."""
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    return users


@app.get("/users/by-role/{role}", tags=["Admin"])
def list_users_by_role(
    role: str,
    db:   Session    = Depends(get_db),
    _:    models.User = Depends(require_role("ADMIN")),
):
    """Admin filters users by role — OWNER / GOVERNMENT / ADMIN."""
    valid_roles = ["OWNER", "GOVERNMENT", "ADMIN"]
    if role.upper() not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Role must be one of {valid_roles}")
    users = db.query(models.User).filter(
        models.User.role == role.upper()
    ).order_by(models.User.created_at.desc()).all()
    return users


@app.put("/users/{user_id}/deactivate", tags=["Admin"])
def deactivate_user(
    user_id:      int,
    db:           Session    = Depends(get_db),
    current_user: models.User = Depends(require_role("ADMIN")),
):
    """
    Admin deactivates any user including Government accounts.
    - Deactivated users cannot login.
    - If Owner: all their REGISTERED properties are FROZEN.
    - If Government: they cannot approve/reject requests.
    """
    user = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is already deactivated")

    user.is_active  = False
    user.updated_at = datetime.utcnow()

    # ── Freeze all properties if Owner ──
    frozen_count = 0
    frozen_ids   = []
    if user.role == "OWNER":
        properties = db.query(models.Property).filter(
            models.Property.current_owner_id == user_id,
            models.Property.status.in_(["REGISTERED", "PENDING", "RESOLVED"])
        ).all()
        for prop in properties:
            prop.status     = "FROZEN"
            prop.updated_at = datetime.utcnow()
            frozen_ids.append(prop.property_id)
            frozen_count += 1

    db.commit()

    # Log this action
    log_activity(
        db,
        actor_id    = current_user.user_id,
        action      = "DEACTIVATE_USER",
        target_type = "USER",
        target_id   = user_id,
        details     = f"Deactivated {user.role} account: {user.full_name} ({user.email}). Properties frozen: {frozen_count}",
    )

    return {
        "message":         f"User '{user.full_name}' deactivated successfully",
        "deactivated_by":  current_user.full_name,
        "role_affected":   user.role,
        "properties_frozen": frozen_count,
        "frozen_property_ids": frozen_ids,
    }


@app.put("/users/{user_id}/reactivate", tags=["Admin"])
def reactivate_user(
    user_id:      int,
    db:           Session    = Depends(get_db),
    current_user: models.User = Depends(require_role("ADMIN")),
):
    """
    Admin reactivates a previously deactivated user.
    - If Owner: all their FROZEN properties are restored to REGISTERED.
    """
    user = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_active:
        raise HTTPException(status_code=400, detail="User is already active")

    user.is_active  = True
    user.updated_at = datetime.utcnow()

    # ── Unfreeze all frozen properties if Owner ──
    unfrozen_count = 0
    unfrozen_ids   = []
    if user.role == "OWNER":
        frozen_props = db.query(models.Property).filter(
            models.Property.current_owner_id == user_id,
            models.Property.status == "FROZEN"
        ).all()
        for prop in frozen_props:
            prop.status     = "REGISTERED"
            prop.updated_at = datetime.utcnow()
            unfrozen_ids.append(prop.property_id)
            unfrozen_count += 1

    db.commit()

    log_activity(
        db,
        actor_id    = current_user.user_id,
        action      = "REACTIVATE_USER",
        target_type = "USER",
        target_id   = user_id,
        details     = f"Reactivated {user.role} account: {user.full_name} ({user.email}). Properties unfrozen: {unfrozen_count}",
    )

    return {
        "message":           f"User '{user.full_name}' reactivated successfully",
        "reactivated_by":    current_user.full_name,
        "role":              user.role,
        "properties_unfrozen": unfrozen_count,
        "unfrozen_property_ids": unfrozen_ids,
    }


# ═══════════════════════════════════════════
# ACTIVITY LOG (Admin only)
# ═══════════════════════════════════════════

@app.get("/admin/activity-log", tags=["Admin"])
def get_activity_log(
    limit:        int        = 100,
    db:           Session    = Depends(get_db),
    _:            models.User = Depends(require_role("ADMIN")),
):
    """Admin views full activity log of all government and admin actions."""
    logs = db.query(models.ActivityLog).order_by(
        models.ActivityLog.created_at.desc()
    ).limit(limit).all()

    result = []
    for log in logs:
        actor = db.query(models.User).filter(
            models.User.user_id == log.actor_id
        ).first()
        result.append({
            "log_id":      log.log_id,
            "actor_id":    log.actor_id,
            "actor_name":  actor.full_name if actor else "Unknown",
            "actor_role":  actor.role      if actor else "Unknown",
            "action":      log.action,
            "target_type": log.target_type,
            "target_id":   log.target_id,
            "details":     log.details,
            "timestamp":   log.created_at,
        })
    return result


@app.get("/admin/government-activity", tags=["Admin"])
def get_government_activity(
    db: Session    = Depends(get_db),
    _:  models.User = Depends(require_role("ADMIN")),
):
    """
    Admin views all actions performed by Government users —
    approvals, rejections, disputes, resolutions.
    """
    # Get all government users
    gov_users = db.query(models.User).filter(
        models.User.role == "GOVERNMENT"
    ).all()
    gov_ids = [u.user_id for u in gov_users]

    # Get their activity logs
    logs = db.query(models.ActivityLog).filter(
        models.ActivityLog.actor_id.in_(gov_ids)
    ).order_by(models.ActivityLog.created_at.desc()).all()

    # Also get approved/rejected requests summary
    approved = db.query(models.PropertyRequest).filter(
        models.PropertyRequest.status == "APPROVED"
    ).count()
    rejected = db.query(models.PropertyRequest).filter(
        models.PropertyRequest.status == "REJECTED"
    ).count()
    pending  = db.query(models.PropertyRequest).filter(
        models.PropertyRequest.status == "PENDING"
    ).count()
    disputed = db.query(models.Property).filter(
        models.Property.status == "DISPUTED"
    ).count()

    result = []
    for log in logs:
        actor = next((u for u in gov_users if u.user_id == log.actor_id), None)
        result.append({
            "log_id":      log.log_id,
            "actor_name":  actor.full_name if actor else "Unknown",
            "actor_email": actor.email     if actor else "Unknown",
            "action":      log.action,
            "target_type": log.target_type,
            "target_id":   log.target_id,
            "details":     log.details,
            "timestamp":   log.created_at,
        })

    return {
        "summary": {
            "total_approved":  approved,
            "total_rejected":  rejected,
            "total_pending":   pending,
            "total_disputed":  disputed,
            "total_gov_users": len(gov_users),
            "total_actions":   len(result),
        },
        "activity": result,
    }


@app.get("/admin/overview", tags=["Admin"])
def admin_overview(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role("ADMIN")),
):
    """Full system overview — Admin only."""
    total_users       = db.query(models.User).count()
    active_users      = db.query(models.User).filter(models.User.is_active == True).count()
    inactive_users    = db.query(models.User).filter(models.User.is_active == False).count()
    owner_count       = db.query(models.User).filter(models.User.role == "OWNER").count()
    gov_count         = db.query(models.User).filter(models.User.role == "GOVERNMENT").count()
    admin_count       = db.query(models.User).filter(models.User.role == "ADMIN").count()
    total_properties  = db.query(models.Property).count()
    on_chain_props    = db.query(models.Property).filter(models.Property.is_on_chain == True).count()
    total_txns        = db.query(models.Transaction).count()
    on_chain_txns     = db.query(models.Transaction).filter(models.Transaction.is_on_chain == True).count()
    open_alerts       = db.query(models.FraudAlert).filter(models.FraudAlert.is_resolved == False).count()
    resolved_alerts   = db.query(models.FraudAlert).filter(models.FraudAlert.is_resolved == True).count()
    pending_requests  = db.query(models.PropertyRequest).filter(models.PropertyRequest.status == "PENDING").count()
    disputed_props    = db.query(models.Property).filter(models.Property.status == "DISPUTED").count()
    frozen_props      = db.query(models.Property).filter(models.Property.status == "FROZEN").count()

    return {
        "users": {
            "total":    total_users,
            "active":   active_users,
            "inactive": inactive_users,
            "owners":   owner_count,
            "government": gov_count,
            "admins":   admin_count,
        },
        "properties": {
            "total":    total_properties,
            "on_chain": on_chain_props,
            "off_chain": total_properties - on_chain_props,
            "disputed": disputed_props,
            "frozen":   frozen_props,
        },
        "transactions": {
            "total":    total_txns,
            "on_chain": on_chain_txns,
        },
        "fraud": {
            "open_alerts":     open_alerts,
            "resolved_alerts": resolved_alerts,
        },
        "requests": {
            "pending": pending_requests,
        },
    }


# ═══════════════════════════════════════════
# PROPERTY REQUESTS (Owner submits)
# ═══════════════════════════════════════════

@app.post("/property-requests", tags=["Owner"])
def submit_property_request(
    payload:      schemas.PropertyRequestCreate,
    db:           Session       = Depends(get_db),
    current_user: models.User   = Depends(require_role("OWNER")),
):
    """Owner submits a request to register a property."""

    duplicate_scan = find_duplicate_records(
        db,
        payload.property_type,
        payload.address,
        payload.area_sqft,
    )

    req = models.PropertyRequest(
        owner_id      = current_user.user_id,
        property_type = payload.property_type,
        address       = payload.address,
        area_sqft     = payload.area_sqft,
        price         = payload.price,
        document_hash = payload.document_hash or duplicate_scan["fingerprint"],
        status        = "PENDING",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    duplicate_property_ids = [prop.property_id for prop in duplicate_scan["properties"]]
    duplicate_request_ids = [scan_req.request_id for scan_req in duplicate_scan["requests"]]
    duplicate_suspected = bool(duplicate_property_ids or duplicate_request_ids)

    if duplicate_suspected:
        description = (
            f"Potential duplicate property request detected for request #{req.request_id}. "
            f"Fingerprint match found against properties {duplicate_property_ids or '[]'} "
            f"and requests {duplicate_request_ids or '[]'}."
        )
        create_fraud_alert(
            db,
            fraud_type="DUPLICATE_PROPERTY",
            description=description,
            risk_score=96.0,
            flagged_user_id=current_user.user_id,
        )
        db.commit()
        log_activity(
            db,
            actor_id=current_user.user_id,
            action="SUBMIT_DUPLICATE_REQUEST",
            target_type="REQUEST",
            target_id=req.request_id,
            details=description,
        )

    return {
        "message": "Property request submitted",
        "request_id": req.request_id,
        "duplicate_suspected": duplicate_suspected,
        "matching_property_ids": duplicate_property_ids,
        "matching_request_ids": duplicate_request_ids,
        "warning": (
            "Potential duplicate detected. Government and admin fraud views have been notified."
            if duplicate_suspected else None
        ),
    }


@app.get("/property-requests/my", tags=["Owner"])
def my_requests(
    db:           Session     = Depends(get_db),
    current_user: models.User = Depends(require_role("OWNER")),
):
    """Owner views their own property requests."""
    return db.query(models.PropertyRequest).filter(
        models.PropertyRequest.owner_id == current_user.user_id
    ).all()


# ═══════════════════════════════════════════
# GOVERNMENT APPROVAL WORKFLOW
# ═══════════════════════════════════════════

@app.get("/government/pending-requests", tags=["Government"])
def get_pending_requests(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role("GOVERNMENT")),
):
    """Government views all pending property registration requests."""
    return db.query(models.PropertyRequest).filter(
        models.PropertyRequest.status == "PENDING"
    ).all()


@app.post("/government/approve/{request_id}", tags=["Government"])
def approve_property_request(
    request_id: int,
    db:         Session    = Depends(get_db),
    gov_user:   models.User = Depends(require_role("GOVERNMENT")),
):
    """
    Government approves a property request.
    Creates the Property in DB AND registers it on the blockchain.
    """
    req = db.query(models.PropertyRequest).filter(
        models.PropertyRequest.request_id == request_id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "PENDING":
        raise HTTPException(status_code=400, detail=f"Request is already {req.status}")

    duplicate_scan = find_duplicate_records(
        db,
        req.property_type,
        req.address,
        req.area_sqft,
        exclude_request_id=req.request_id,
    )
    duplicate_properties = duplicate_scan["properties"]
    duplicate_requests = duplicate_scan["requests"]
    if duplicate_properties or duplicate_requests:
        duplicate_property_ids = [prop.property_id for prop in duplicate_properties]
        duplicate_request_ids = [dup_req.request_id for dup_req in duplicate_requests]
        description = (
            f"Government blocked duplicate property approval attempt for request #{req.request_id}. "
            f"Matches found in properties {duplicate_property_ids or '[]'} "
            f"and requests {duplicate_request_ids or '[]'}."
        )
        req.status = "REJECTED"
        req.reject_reason = "Duplicate property fingerprint detected. Manual fraud review required."
        create_fraud_alert(
            db,
            fraud_type="DUPLICATE_PROPERTY",
            description=description,
            risk_score=99.0,
            flagged_user_id=req.owner_id,
            property_id=duplicate_property_ids[0] if duplicate_property_ids else None,
        )
        db.commit()
        log_activity(
            db,
            actor_id=gov_user.user_id,
            action="BLOCK_DUPLICATE_REQUEST",
            target_type="REQUEST",
            target_id=request_id,
            details=description,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Duplicate property fingerprint detected. Approval blocked and fraud alert raised "
                f"(properties: {duplicate_property_ids or []}, requests: {duplicate_request_ids or []})."
            ),
        )

    # Get owner
    owner = db.query(models.User).filter(models.User.user_id == req.owner_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Owner user not found")

    # Create property in DB
    reg_number = generate_registration_number(db)
    prop = models.Property(
        registration_number = reg_number,
        property_type       = req.property_type,
        address             = req.address,
        area_sqft           = req.area_sqft,
        price               = req.price,
        current_owner_id    = req.owner_id,
        status              = "REGISTERED",
        is_on_chain         = False,
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)

    # Register on blockchain
    try:
        tx_hash = register_property_on_chain(
            property_id   = prop.property_id,
            address_text  = req.address,
            price         = int(req.price),
            owner_wallet  = owner.wallet_address,
        )
        prop.blockchain_tx_hash = tx_hash
        prop.is_on_chain        = True

        # Genesis transaction record
        txn = models.Transaction(
            property_id      = prop.property_id,
            sender_id        = gov_user.user_id,
            receiver_id      = req.owner_id,
            amount           = req.price,
            payment_mode     = "ONLINE",
            transaction_type = "REGISTER",
            blockchain_tx_hash = tx_hash,
            is_on_chain      = True,
        )
        db.add(txn)

    except Exception as e:
        # Blockchain failed — mark but don't rollback DB registration
        prop.blockchain_tx_hash = None
        prop.is_on_chain        = False
        print(f"⚠️  Blockchain registration failed: {e}")

    req.status = "APPROVED"
    db.commit()

    # Log government action
    log_activity(
        db,
        actor_id    = gov_user.user_id,
        action      = "APPROVE_REQUEST",
        target_type = "REQUEST",
        target_id   = request_id,
        details     = f"Approved property request #{request_id} → Property #{prop.property_id} ({prop.address}). On chain: {prop.is_on_chain}",
    )

    return {
        "message":      "Property approved and registered",
        "property_id":  prop.property_id,
        "reg_number":   reg_number,
        "on_chain":     prop.is_on_chain,
        "tx_hash":      prop.blockchain_tx_hash,
    }


@app.post("/government/reject/{request_id}", tags=["Government"])
def reject_property_request(
    request_id: int,
    payload:    schemas.RejectRequest,
    db:         Session    = Depends(get_db),
    gov_user:   models.User = Depends(require_role("GOVERNMENT")),
):
    req = db.query(models.PropertyRequest).filter(
        models.PropertyRequest.request_id == request_id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "PENDING":
        raise HTTPException(status_code=400, detail=f"Request is already {req.status}")

    req.status        = "REJECTED"
    req.reject_reason = payload.reason
    db.commit()

    # Log government action
    log_activity(
        db,
        actor_id    = gov_user.user_id,
        action      = "REJECT_REQUEST",
        target_type = "REQUEST",
        target_id   = request_id,
        details     = f"Rejected property request #{request_id}. Reason: {payload.reason}",
    )

    return {"message": "Request rejected", "reason": payload.reason}


# ═══════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════

@app.get("/properties/frozen", tags=["Admin"])
def get_frozen_properties(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role("ADMIN")),
):
    """Admin views all frozen properties — owners were deactivated."""
    props = db.query(models.Property).filter(
        models.Property.status == "FROZEN"
    ).all()

    result = []
    for p in props:
        owner = db.query(models.User).filter(
            models.User.user_id == p.current_owner_id
        ).first()
        result.append({
            "property_id":       p.property_id,
            "registration_number": p.registration_number,
            "address":           p.address,
            "property_type":     p.property_type,
            "area_sqft":         p.area_sqft,
            "price":             p.price,
            "status":            p.status,
            "is_on_chain":       p.is_on_chain,
            "owner_id":          p.current_owner_id,
            "owner_name":        owner.full_name  if owner else "Unknown",
            "owner_email":       owner.email      if owner else "Unknown",
            "owner_active":      owner.is_active  if owner else False,
            "frozen_since":      p.updated_at,
        })
    return result


@app.get("/properties", tags=["Properties"])
def list_all_properties(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return db.query(models.Property).all()


@app.get("/properties/user/{user_id}", tags=["Properties"])
def get_user_properties(
    user_id: int,
    db:      Session    = Depends(get_db),
    current: models.User = Depends(get_current_user),
):
    """Owner views their own properties. Admin/Gov can view any user's properties."""
    if current.role == "OWNER" and current.user_id != user_id:
        raise HTTPException(status_code=403, detail="Cannot view other users' properties")

    return db.query(models.Property).filter(
        models.Property.current_owner_id == user_id
    ).all()


@app.get("/properties/{property_id}", tags=["Properties"])
def get_property(
    property_id: int,
    db:          Session    = Depends(get_db),
    _:           models.User = Depends(get_current_user),
):
    prop = db.query(models.Property).filter(
        models.Property.property_id == property_id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


@app.get("/properties/{property_id}/verify", tags=["Properties"])
def verify_property(
    property_id: int,
    db:          Session    = Depends(get_db),
    _:           models.User = Depends(get_current_user),
):
    """Compares DB owner vs blockchain owner."""
    prop = db.query(models.Property).filter(
        models.Property.property_id == property_id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if not prop.is_on_chain:
        return {
            "property_id": property_id,
            "status":      "NOT_ON_CHAIN",
            "message":     "Property has not been registered on blockchain yet",
        }

    try:
        chain_data   = verify_property_on_chain(property_id)
        db_wallet    = prop.owner.wallet_address.lower()
        chain_wallet = chain_data["owner"].lower()
        match        = db_wallet == chain_wallet

        return {
            "property_id":     property_id,
            "database_owner":  db_wallet,
            "blockchain_owner": chain_wallet,
            "is_verified":     chain_data["is_verified"],
            "is_disputed":     chain_data["is_disputed"],
            "match":           match,
            "status":          "MATCH" if match else "MISMATCH",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Blockchain read failed: {str(e)}")


@app.get("/properties/{property_id}/timeline", tags=["Properties"])
def property_timeline(
    property_id: int,
    db:          Session    = Depends(get_db),
    _:           models.User = Depends(get_current_user),
):
    """
    Returns property ownership timeline.
    Source of truth = blockchain (if on chain), fallback = DB.
    """
    prop = db.query(models.Property).filter(
        models.Property.property_id == property_id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if prop.is_on_chain:
        try:
            timeline = get_property_history_from_chain(property_id)
            return {"property_id": property_id, "source": "blockchain", "timeline": timeline}
        except Exception as e:
            print(f"⚠️  Chain timeline failed, falling back to DB: {e}")

    # DB fallback
    txns = db.query(models.Transaction).filter(
        models.Transaction.property_id == property_id
    ).order_by(models.Transaction.timestamp).all()

    timeline = []
    for t in txns:
        timeline.append({
            "from":          t.sender_id,
            "to":            t.receiver_id,
            "price":         t.amount,
            "readable_time": t.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "tx_hash":       t.blockchain_tx_hash or "—",
            "tx_type":       t.transaction_type,
        })

    return {"property_id": property_id, "source": "database", "timeline": timeline}


# ═══════════════════════════════════════════
# TRANSFER (Owner initiates — Gov signs on chain)
# ═══════════════════════════════════════════

@app.post("/properties/transfer", tags=["Owner"])
def transfer_property(
    payload:      schemas.TransferRequest,
    db:           Session     = Depends(get_db),
    current_user: models.User = Depends(require_role("OWNER")),
):
    """
    Owner requests property transfer.
    Backend (government wallet) signs and sends the blockchain transaction.
    """
    prop = db.query(models.Property).filter(
        models.Property.property_id == payload.property_id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.current_owner_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="You do not own this property")
    if prop.status == "DISPUTED":
        raise HTTPException(status_code=400, detail="Cannot transfer a disputed property")
    if prop.status == "FROZEN":
        raise HTTPException(status_code=400, detail="Cannot transfer a frozen property. Owner account is deactivated.")

    receiver = db.query(models.User).filter(
        models.User.user_id == payload.receiver_id
    ).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver user not found")

    # ── Blockchain transfer (government wallet signs) ──
    tx_hash  = None
    on_chain = False

    if prop.is_on_chain:
        try:
            tx_hash = transfer_property_on_chain(
                property_id      = prop.property_id,
                new_owner_wallet = receiver.wallet_address,
                price            = int(payload.amount),
            )
            on_chain = True
        except Exception as e:
            print(f"⚠️  Blockchain transfer failed: {e}")
            tx_hash = generate_tx_hash(
                f"{prop.property_id}{current_user.user_id}{payload.receiver_id}"
            )

    # ── Update DB ──
    prop.current_owner_id = payload.receiver_id
    prop.updated_at       = datetime.utcnow()

    txn = models.Transaction(
        property_id        = prop.property_id,
        sender_id          = current_user.user_id,
        receiver_id        = payload.receiver_id,
        amount             = payload.amount,
        payment_mode       = payload.payment_mode,
        transaction_type   = "TRANSFER",
        blockchain_tx_hash = tx_hash,
        is_on_chain        = on_chain,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    return {
        "message":        "Transfer successful",
        "transaction_id": txn.transaction_id,
        "blockchain_hash": tx_hash,
        "on_chain":       on_chain,
    }


# ═══════════════════════════════════════════
# DISPUTES (Government manages)
# ═══════════════════════════════════════════

@app.post("/properties/dispute", tags=["Government"])
def raise_dispute(
    payload:  schemas.DisputeRequest,
    db:       Session    = Depends(get_db),
    gov_user: models.User = Depends(require_role("GOVERNMENT")),
):
    prop = db.query(models.Property).filter(
        models.Property.property_id == payload.property_id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    prop.status     = "DISPUTED"
    prop.updated_at = datetime.utcnow()

    tx_hash = None
    if prop.is_on_chain:
        try:
            tx_hash = raise_dispute_on_chain(payload.property_id)
        except Exception as e:
            print(f"⚠️  Blockchain dispute failed: {e}")

    alert = models.FraudAlert(
        property_id     = payload.property_id,
        fraud_type      = "CIRCULAR_OWNERSHIP",
        risk_score      = 100.0,
        description     = payload.reason,
        flagged_user_id = prop.current_owner_id,
    )
    db.add(alert)
    db.commit()

    # Log government action
    log_activity(
        db,
        actor_id    = gov_user.user_id,
        action      = "RAISE_DISPUTE",
        target_type = "PROPERTY",
        target_id   = payload.property_id,
        details     = f"Dispute raised on property #{payload.property_id} ({prop.address}). Reason: {payload.reason}",
    )

    return {
        "message":  "Dispute raised",
        "tx_hash":  tx_hash,
        "on_chain": tx_hash is not None,
    }


@app.post("/properties/resolve-dispute", tags=["Government"])
def resolve_dispute(
    payload:  schemas.ResolveDisputeRequest,
    db:       Session    = Depends(get_db),
    gov_user: models.User = Depends(require_role("GOVERNMENT")),
):
    prop = db.query(models.Property).filter(
        models.Property.property_id == payload.property_id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.status != "DISPUTED":
        raise HTTPException(status_code=400, detail="Property is not under dispute")

    prop.status     = "RESOLVED"
    prop.updated_at = datetime.utcnow()

    tx_hash = None
    if prop.is_on_chain:
        try:
            tx_hash = resolve_dispute_on_chain(payload.property_id)
        except Exception as e:
            print(f"⚠️  Blockchain resolve failed: {e}")

    db.commit()

    # Log government action
    log_activity(
        db,
        actor_id    = gov_user.user_id,
        action      = "RESOLVE_DISPUTE",
        target_type = "PROPERTY",
        target_id   = payload.property_id,
        details     = f"Dispute resolved on property #{payload.property_id} ({prop.address})",
    )

    return {"message": "Dispute resolved", "tx_hash": tx_hash}


# ═══════════════════════════════════════════
# TRANSACTIONS
# ═══════════════════════════════════════════

@app.get("/transactions", tags=["Transactions"])
def get_transactions(
    db:      Session    = Depends(get_db),
    current: models.User = Depends(get_current_user),
):
    """
    Owners see only their own transactions.
    Government / Admin see all.
    """
    Sender   = aliased(models.User)
    Receiver = aliased(models.User)

    q = db.query(
        models.Transaction,
        models.Property.registration_number,
        models.Property.address,
        Sender.full_name.label("sender_name"),
        Sender.email.label("sender_email"),
        Receiver.full_name.label("receiver_name"),
        Receiver.email.label("receiver_email"),
    ).join(
        models.Property, models.Transaction.property_id == models.Property.property_id
    ).join(
        Sender, models.Transaction.sender_id == Sender.user_id
    ).join(
        Receiver, models.Transaction.receiver_id == Receiver.user_id
    )

    if current.role == "OWNER":
        q = q.filter(
            (models.Transaction.sender_id == current.user_id) |
            (models.Transaction.receiver_id == current.user_id)
        )

    rows = q.order_by(models.Transaction.timestamp.desc()).all()

    result = []
    for row in rows:
        txn = row[0]
        result.append({
            "transaction_id":   txn.transaction_id,
            "property":         f"{row[1]} ({row[2]})",
            "sender_id":        txn.sender_id,
            "receiver_id":      txn.receiver_id,
            "from_user":        f"{row[3]} ({row[4]})",
            "to_user":          f"{row[5]} ({row[6]})",
            "amount":           txn.amount,
            "payment_mode":     txn.payment_mode,
            "transaction_type": txn.transaction_type,
            "blockchain_hash":  txn.blockchain_tx_hash,
            "is_on_chain":      txn.is_on_chain,
            "time":             txn.timestamp,
        })

    return result


# ═══════════════════════════════════════════
# FRAUD DETECTION (Admin / Government)
# ═══════════════════════════════════════════

@app.get("/fraud/analyze", tags=["Fraud"])
def analyze_fraud(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role("ADMIN", "GOVERNMENT")),
):
    """Run full fraud analysis — DBSCAN + Louvain + 4 extra signals."""
    try:
        return run_fraud_analysis(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fraud analysis failed: {str(e)}")


@app.get("/fraud/alerts", tags=["Fraud"])
def get_fraud_alerts(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role("ADMIN", "GOVERNMENT")),
):
    """Get all unresolved fraud alerts."""
    alerts = db.query(models.FraudAlert).filter(
        models.FraudAlert.is_resolved == False
    ).order_by(models.FraudAlert.risk_score.desc()).all()
    return alerts


@app.put("/fraud/alerts/{alert_id}/resolve", tags=["Fraud"])
def resolve_alert(
    alert_id:     int,
    db:           Session    = Depends(get_db),
    current_user: models.User = Depends(require_role("ADMIN", "GOVERNMENT")),
):
    alert = db.query(models.FraudAlert).filter(
        models.FraudAlert.alert_id == alert_id
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.is_resolved = True
    alert.resolved_by = current_user.user_id
    alert.resolved_at = datetime.utcnow()
    db.commit()
    return {"message": "Alert resolved"}


# ═══════════════════════════════════════════
# BLOCKCHAIN STATS (Admin + Government)
# ═══════════════════════════════════════════

@app.get("/blockchain/stats", tags=["Blockchain"])
def blockchain_stats(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role("ADMIN", "GOVERNMENT")),
):
    """
    Combined blockchain stats — live from smart contract + DB sync status.
    Shows both on-chain data AND DB records for comparison.
    """
    # ── DB stats ──
    db_total_props    = db.query(models.Property).count()
    db_on_chain_props = db.query(models.Property).filter(
        models.Property.is_on_chain == True
    ).count()
    db_total_txns    = db.query(models.Transaction).count()
    db_on_chain_txns = db.query(models.Transaction).filter(
        models.Transaction.is_on_chain == True
    ).count()

    # ── Live chain stats ──
    chain_data = {}
    chain_error = None
    try:
        chain_data = get_chain_stats()
    except Exception as e:
        chain_error = str(e)

    return {
        "contract_address":    chain_data.get("contract_address", "N/A"),
        "government_address":  chain_data.get("government_address", "N/A"),
        "signer_address":      chain_data.get("signer_address", "N/A"),
        "network":             "Sepolia Testnet",

        # Live from smart contract
        "chain": {
            "total_properties":   chain_data.get("total_properties", 0),
            "total_transactions": chain_data.get("total_transactions", 0),
            "error":              chain_error,
        },

        # From our database
        "database": {
            "total_properties":    db_total_props,
            "on_chain_properties": db_on_chain_props,
            "off_chain_properties": db_total_props - db_on_chain_props,
            "total_transactions":  db_total_txns,
            "on_chain_transactions": db_on_chain_txns,
        },

        # Sync status
        "sync_status": {
            "properties_synced":   chain_data.get("total_properties", 0) == db_on_chain_props,
            "note": "Chain shows only properties registered via this backend. Seeded test data exists in DB only."
        }
    }


@app.get("/admin/chart-analysis", tags=["Admin"])
def admin_chart_analysis(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role("ADMIN")),
):
    users = {
        user.user_id: user
        for user in db.query(models.User).all()
    }
    transactions = db.query(models.Transaction).order_by(models.Transaction.timestamp.asc()).all()
    unresolved_alerts = db.query(models.FraudAlert).filter(
        models.FraudAlert.is_resolved == False
    ).all()

    ring_types = {"CIRCULAR_OWNERSHIP", "HIGH_FREQ_PAIR", "SELF_DEALING"}
    suspicious_user_ids = set()
    suspicious_tx_ids = set()

    fraud_frequency: dict[str, int] = {}
    risk_counts = {"Low": 0, "Medium": 0, "High": 0}

    for alert in unresolved_alerts:
        fraud_frequency[alert.fraud_type] = fraud_frequency.get(alert.fraud_type, 0) + 1
        risk_counts[risk_bucket(alert.risk_score)] += 1

        if alert.fraud_type in ring_types and alert.flagged_user_id:
            suspicious_user_ids.add(alert.flagged_user_id)
        if alert.transaction_id:
            suspicious_tx_ids.add(alert.transaction_id)

    node_map: dict[int, dict] = {}
    edge_map: dict[tuple[int, int], dict] = {}

    for txn in transactions:
        sender = users.get(txn.sender_id)
        receiver = users.get(txn.receiver_id)

        for uid, user in ((txn.sender_id, sender), (txn.receiver_id, receiver)):
            if uid not in node_map:
                is_suspicious = uid in suspicious_user_ids
                node_map[uid] = {
                    "id": uid,
                    "label": user.full_name if user else f"User {uid}",
                    "title": (
                        f"{user.full_name if user else f'User {uid}'}"
                        f"<br>{user.role if user else 'UNKNOWN'}"
                        f"<br>{user.email if user else 'No email'}"
                    ),
                    "group": (user.role if user else "UNKNOWN").lower(),
                    "value": 1,
                    "color": {
                        "background": "#fee2e2" if is_suspicious else (
                            "#ede9fe" if user and user.role == "ADMIN" else
                            "#dcfce7" if user and user.role == "GOVERNMENT" else
                            "#dbeafe"
                        ),
                        "border": "#dc2626" if is_suspicious else (
                            "#7c3aed" if user and user.role == "ADMIN" else
                            "#059669" if user and user.role == "GOVERNMENT" else
                            "#2563eb"
                        ),
                    },
                    "font": {"color": "#111827"},
                    "suspicious": is_suspicious,
                }
            node_map[uid]["value"] += 1

        key = (txn.sender_id, txn.receiver_id)
        if key not in edge_map:
            edge_map[key] = {
                "from": txn.sender_id,
                "to": txn.receiver_id,
                "label": "1 tx",
                "value": 1,
                "amount_total": 0,
                "property_ids": set(),
                "transaction_ids": [],
                "suspicious": False,
                "color": {"color": "#94a3b8"},
                "arrows": "to",
                "smooth": {"type": "curvedCW", "roundness": 0.18},
            }

        edge = edge_map[key]
        edge["value"] += 1
        edge["amount_total"] += float(txn.amount or 0)
        edge["property_ids"].add(txn.property_id)
        edge["transaction_ids"].append(txn.transaction_id)

        tx_is_suspicious = (
            txn.transaction_id in suspicious_tx_ids or
            txn.sender_id in suspicious_user_ids or
            txn.receiver_id in suspicious_user_ids
        )
        if tx_is_suspicious:
            edge["suspicious"] = True
            edge["color"] = {"color": "#dc2626"}
            node_map[txn.sender_id]["suspicious"] = True
            node_map[txn.receiver_id]["suspicious"] = True
            node_map[txn.sender_id]["color"] = {"background": "#fee2e2", "border": "#dc2626"}
            node_map[txn.receiver_id]["color"] = {"background": "#fee2e2", "border": "#dc2626"}

    network_nodes = list(node_map.values())
    network_edges = []
    for edge in edge_map.values():
        tx_count = len(edge["transaction_ids"])
        property_count = len(edge["property_ids"])
        edge["label"] = f"{tx_count} tx"
        edge["title"] = (
            f"{tx_count} transaction(s)"
            f"<br>Total value: Rs. {edge['amount_total']:,.0f}"
            f"<br>Properties involved: {property_count}"
            f"{'<br>Flagged as suspicious' if edge['suspicious'] else ''}"
        )
        edge["width"] = 2 + min(tx_count, 6)
        edge["property_ids"] = sorted(edge["property_ids"])
        network_edges.append(edge)

    metrics = load_evaluation_metrics()
    metric_labels = ["Precision", "Recall", "F1-score", "AUC"]
    metric_keys = ["precision", "recall", "f1", "auc"]
    metric_values = []
    for key in metric_keys:
        value = metrics.get(key)
        metric_values.append(round(float(value) * 100, 2) if isinstance(value, (int, float)) else None)

    return {
        "network_graph": {
            "nodes": network_nodes,
            "edges": network_edges,
            "summary": {
                "entities": len(network_nodes),
                "transaction_links": len(network_edges),
                "ring_entities": sum(1 for node in network_nodes if node.get("suspicious")),
                "suspicious_links": sum(1 for edge in network_edges if edge.get("suspicious")),
            },
        },
        "risk_score_distribution": [
            {"label": label, "value": risk_counts[label]}
            for label in ["Low", "Medium", "High"]
        ],
        "performance_metrics": {
            "available": metrics.get("available", False),
            "message": metrics.get("message"),
            "labels": metric_labels,
            "values": metric_values,
        },
        "fraud_signal_frequency": [
            {"label": fraud_type.replace("_", " "), "value": count}
            for fraud_type, count in sorted(fraud_frequency.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


@app.get("/blockchain/records", tags=["Blockchain"])
def blockchain_records(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role("ADMIN", "GOVERNMENT")),
):
    """
    Returns detailed evidence for properties marked on-chain in the DB.
    Only fields truly available from the current contract are exposed as on-chain facts.
    Hash-chain fields are reported as unavailable until the contract stores them explicitly.
    """
    props = db.query(models.Property).filter(
        models.Property.is_on_chain == True
    ).order_by(models.Property.created_at.desc()).all()

    records = []
    for prop in props:
        owner = db.query(models.User).filter(
            models.User.user_id == prop.current_owner_id
        ).first()
        txns = db.query(models.Transaction).filter(
            models.Transaction.property_id == prop.property_id
        ).order_by(models.Transaction.timestamp.desc()).all()
        latest_db_tx = next((tx for tx in txns if tx.blockchain_tx_hash), None)

        chain_available = False
        chain_error = None
        chain_details = None
        chain_timeline = []
        chain_audit_trail = []

        try:
            chain_details = get_property_details_from_chain(prop.property_id)
            chain_timeline = get_property_history_from_chain(prop.property_id)
            chain_audit_trail = get_property_audit_trail_from_chain(prop.property_id)
            chain_available = True
        except Exception as e:
            chain_error = str(e)

        latest_audit = chain_audit_trail[-1] if chain_audit_trail else None

        records.append({
            "property_id": prop.property_id,
            "registration_number": prop.registration_number,
            "address": prop.address,
            "property_type": prop.property_type,
            "price": prop.price,
            "db_owner_id": prop.current_owner_id,
            "db_owner_name": owner.full_name if owner else "Unknown",
            "db_owner_wallet": owner.wallet_address if owner else None,
            "db_status": prop.status,
            "db_created_at": prop.created_at,
            "db_updated_at": prop.updated_at,
            "db_blockchain_tx_hash": prop.blockchain_tx_hash or (latest_db_tx.blockchain_tx_hash if latest_db_tx else None),
            "contract_address": CONTRACT_ADDRESS,
            "chain_available": chain_available,
            "chain_error": chain_error,
            "chain_current_owner": chain_details["current_owner"] if chain_details else None,
            "chain_price": chain_details["price"] if chain_details else None,
            "chain_created_at": chain_details["created_at_readable"] if chain_details else None,
            "chain_updated_at": chain_details["updated_at_readable"] if chain_details else None,
            "chain_is_verified": chain_details["is_verified"] if chain_details else None,
            "chain_is_disputed": chain_details["is_disputed"] if chain_details else None,
            "timeline": chain_timeline,
            "audit_trail": chain_audit_trail,
            "current_state_hash": latest_audit["current_data_hash"] if latest_audit else build_property_state_hash(prop),
            "previous_state_hash": latest_audit["previous_data_hash"] if latest_audit and latest_audit["previous_data_hash"] != "0000000000000000000000000000000000000000000000000000000000000000" else None,
            "block_fingerprint": latest_audit["block_fingerprint"] if latest_audit else None,
            "previous_state_hash_note": (
                "Fetched from on-chain audit records." if latest_audit
                else "Computed from database history for display only. Redeploy the upgraded contract to store real hash-linked records on-chain."
            ),
        })

    return {
        "count": len(records),
        "records": records,
        "limitations": [
            "Current deployed contract may not yet expose on-chain audit hashes until you redeploy the upgraded version.",
            "Tx hash is available from the blockchain transaction receipt / database record, not as EVM contract storage.",
            "After redeploy, currentDataHash, previousDataHash, and blockFingerprint will be read directly from chain storage.",
        ],
    }
