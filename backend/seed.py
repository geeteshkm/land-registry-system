"""
Database Seeder Script
======================
Populates the database with realistic test data including
deliberately suspicious transactions to trigger all 6 fraud signals.

Run from backend folder:
    python seed.py

What gets created:
    - 12 users (1 admin, 1 gov, 10 owners)
    - 8 properties
    - 25+ transactions with fraud patterns:
        1. AMOUNT_ANOMALY     — one transaction with suspiciously high amount
        2. CIRCULAR_OWNERSHIP — A → B → C → A ownership chain
        3. RAPID_TRANSFER     — property sold twice within 2 days
        4. PRICE_MANIPULATION — property price jumps 5x in one transfer
        5. SELF_DEALING       — two accounts with same wallet address
        6. HIGH_FREQ_PAIR     — same two users transact 5 times
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
try:
    from .database import SessionLocal, engine, Base
    from .auth import hash_password
    from . import models
except ImportError:
    from database import SessionLocal, engine, Base
    from auth import hash_password
    import models
import hashlib
import random

# ─────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────

Base.metadata.create_all(bind=engine)
db = SessionLocal()

def fake_tx_hash(data: str) -> str:
    """Generate a realistic-looking blockchain tx hash."""
    return "0x" + hashlib.sha256(f"{data}{random.random()}".encode()).hexdigest()

def fake_wallet(seed: str) -> str:
    """Generate a realistic-looking Ethereum wallet address."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return "0x" + h[:40]

def fake_reg_number(n: int) -> str:
    return f"REG2024{str(n).zfill(5)}"

def ago(days=0, hours=0, minutes=0) -> datetime:
    return datetime.utcnow() - timedelta(days=days, hours=hours, minutes=minutes)

print("🌱 Starting database seeder...")
print("─" * 50)

# ─────────────────────────────────────────
# CLEAR EXISTING DATA (safe order)
# ─────────────────────────────────────────

print("🗑️  Clearing existing data...")
db.query(models.ActivityLog).delete()
db.query(models.FraudAlert).delete()
db.query(models.Transaction).delete()
db.query(models.PropertyRequest).delete()
db.query(models.Property).delete()
db.query(models.User).delete()
db.commit()
print("✅ Cleared.")

# ─────────────────────────────────────────
# USERS
# ─────────────────────────────────────────

print("\n👤 Creating users...")

users_data = [
    # system users
    { "full_name": "System Admin",        "email": "admin@blrs.com",   "password": "admin123",  "role": "ADMIN",      "wallet": fake_wallet("admin_wallet_seed_001"),    "phone": "1111111111" },
    { "full_name": "Government Authority", "email": "gov@blrs.com",     "password": "gov123",    "role": "GOVERNMENT", "wallet": "0xe62c3708ea4ec963e9f672fbefb6362b8e5af273", "phone": "2222222222" },

    # normal owners
    { "full_name": "Arjun Sharma",        "email": "arjun@test.com",   "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("arjun_wallet_001"),          "phone": "9876543210" },
    { "full_name": "Priya Nair",          "email": "priya@test.com",   "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("priya_wallet_002"),          "phone": "9876543211" },
    { "full_name": "Ravi Kumar",          "email": "ravi@test.com",    "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("ravi_wallet_003"),           "phone": "9876543212" },
    { "full_name": "Meena Iyer",          "email": "meena@test.com",   "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("meena_wallet_004"),          "phone": "9876543213" },
    { "full_name": "Suresh Babu",         "email": "suresh@test.com",  "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("suresh_wallet_005"),         "phone": "9876543214" },
    { "full_name": "Kavitha Reddy",       "email": "kavitha@test.com", "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("kavitha_wallet_006"),        "phone": "9876543215" },
    { "full_name": "Mohan Das",           "email": "mohan@test.com",   "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("mohan_wallet_007"),          "phone": "9876543216" },
    { "full_name": "Lakshmi Patel",       "email": "lakshmi@test.com", "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("lakshmi_wallet_008"),        "phone": "9876543217" },

    # FRAUD PATTERN 5: Self-dealing shell account (unique wallet but same person)
    { "full_name": "Arjun Shell Account", "email": "arjun2@test.com",  "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("arjun_shell_wallet_999"),    "phone": "9999999999" },

    # extra owner
    { "full_name": "Vijay Menon",         "email": "vijay@test.com",   "password": "pass123",   "role": "OWNER",      "wallet": fake_wallet("vijay_wallet_010"),          "phone": "9876543219" },
]

created_users = []
for ud in users_data:
    user = models.User(
        full_name      = ud["full_name"],
        email          = ud["email"],
        password_hash  = hash_password(ud["password"]),
        role           = ud["role"],
        wallet_address = ud["wallet"],
        phone          = ud["phone"],
        is_active      = True,
        created_at     = ago(days=random.randint(30, 90)),
    )
    db.add(user)
    db.flush()
    created_users.append(user)
    print(f"   ✅ {user.full_name} (ID:{user.user_id}) [{user.role}]")

db.commit()

# Shorthand references
ADMIN  = created_users[0]
GOV    = created_users[1]
ARJUN  = created_users[2]   # owner 1
PRIYA  = created_users[3]   # owner 2
RAVI   = created_users[4]   # owner 3
MEENA  = created_users[5]   # owner 4
SURESH = created_users[6]   # owner 5
KAVITA = created_users[7]   # owner 6
MOHAN  = created_users[8]   # owner 7
LAKSHMI= created_users[9]   # owner 8
ARJUN2 = created_users[10]  # shell account (same wallet as ARJUN)
VIJAY  = created_users[11]  # owner 10

# ─────────────────────────────────────────
# PROPERTIES
# ─────────────────────────────────────────

print("\n🏠 Creating properties...")

properties_data = [
    { "reg": fake_reg_number(1), "type": "RESIDENTIAL",  "address": "12 Anna Nagar, Chennai, Tamil Nadu",         "area": 2400,  "price": 4500000,  "owner": ARJUN,   "status": "REGISTERED", "days_ago": 60 },
    { "reg": fake_reg_number(2), "type": "COMMERCIAL",   "address": "45 T Nagar, Chennai, Tamil Nadu",            "area": 5000,  "price": 12000000, "owner": PRIYA,   "status": "REGISTERED", "days_ago": 55 },
    { "reg": fake_reg_number(3), "type": "RESIDENTIAL",  "address": "78 Velachery Main Road, Chennai",            "area": 1800,  "price": 3200000,  "owner": RAVI,    "status": "REGISTERED", "days_ago": 50 },
    { "reg": fake_reg_number(4), "type": "AGRICULTURAL", "address": "Survey No 123, Tambaram, Chennai",           "area": 43560, "price": 8000000,  "owner": MEENA,   "status": "REGISTERED", "days_ago": 45 },
    { "reg": fake_reg_number(5), "type": "RESIDENTIAL",  "address": "23 Adyar, Chennai, Tamil Nadu",             "area": 3200,  "price": 6500000,  "owner": SURESH,  "status": "REGISTERED", "days_ago": 40 },
    { "reg": fake_reg_number(6), "type": "COMMERCIAL",   "address": "67 Nungambakkam High Road, Chennai",         "area": 8000,  "price": 25000000, "owner": KAVITA,  "status": "REGISTERED", "days_ago": 35 },
    { "reg": fake_reg_number(7), "type": "RESIDENTIAL",  "address": "34 Porur, Chennai, Tamil Nadu",             "area": 2100,  "price": 3800000,  "owner": MOHAN,   "status": "DISPUTED",   "days_ago": 30 },
    { "reg": fake_reg_number(8), "type": "AGRICULTURAL", "address": "Plot 56, Maraimalai Nagar, Chengalpattu",   "area": 87120, "price": 15000000, "owner": LAKSHMI, "status": "REGISTERED", "days_ago": 25 },
]

created_props = []
for pd in properties_data:
    prop = models.Property(
        registration_number = pd["reg"],
        property_type       = pd["type"],
        address             = pd["address"],
        area_sqft           = pd["area"],
        price               = pd["price"],
        current_owner_id    = pd["owner"].user_id,
        status              = pd["status"],
        blockchain_tx_hash  = fake_tx_hash(pd["reg"] + "_register"),
        is_on_chain         = True,
        created_at          = ago(days=pd["days_ago"]),
        updated_at          = ago(days=pd["days_ago"]),
    )
    db.add(prop)
    db.flush()
    created_props.append(prop)
    print(f"   ✅ Property #{prop.property_id} — {prop.address[:40]}… [{prop.status}]")

db.commit()

P1, P2, P3, P4, P5, P6, P7, P8 = created_props

# ─────────────────────────────────────────
# PROPERTY REQUESTS (some pending)
# ─────────────────────────────────────────

print("\n📋 Creating property requests...")

req_data = [
    { "owner": VIJAY,  "type": "RESIDENTIAL",  "address": "89 Sholinganallur, Chennai", "area": 1600, "price": 2800000, "status": "PENDING",  "days_ago": 5 },
    { "owner": ARJUN,  "type": "COMMERCIAL",   "address": "12 OMR, Chennai",            "area": 3500, "price": 9000000, "status": "PENDING",  "days_ago": 3 },
    { "owner": PRIYA,  "type": "AGRICULTURAL", "address": "Village Rd, Kancheepuram",   "area": 21780,"price": 5000000, "status": "APPROVED", "days_ago": 20 },
    { "owner": RAVI,   "type": "RESIDENTIAL",  "address": "45 Chromepet, Chennai",      "area": 2200, "price": 4000000, "status": "REJECTED", "days_ago": 15 },
]

for rd in req_data:
    req = models.PropertyRequest(
        owner_id      = rd["owner"].user_id,
        property_type = rd["type"],
        address       = rd["address"],
        area_sqft     = rd["area"],
        price         = rd["price"],
        document_hash = hashlib.sha256(f"{rd['address']}{rd['owner'].user_id}".encode()).hexdigest(),
        status        = rd["status"],
        reject_reason = "Incomplete documentation" if rd["status"] == "REJECTED" else None,
        created_at    = ago(days=rd["days_ago"]),
    )
    db.add(req)

db.commit()
print(f"   ✅ 4 property requests created (2 pending, 1 approved, 1 rejected)")

# ─────────────────────────────────────────
# TRANSACTIONS — NORMAL
# ─────────────────────────────────────────

print("\n💸 Creating normal transactions...")

normal_txns = [
    # Genesis registrations
    { "prop": P1, "sender": GOV,   "receiver": ARJUN,  "amount": 4500000,  "type": "REGISTER", "days_ago": 60 },
    { "prop": P2, "sender": GOV,   "receiver": PRIYA,  "amount": 12000000, "type": "REGISTER", "days_ago": 55 },
    { "prop": P3, "sender": GOV,   "receiver": RAVI,   "amount": 3200000,  "type": "REGISTER", "days_ago": 50 },
    { "prop": P4, "sender": GOV,   "receiver": MEENA,  "amount": 8000000,  "type": "REGISTER", "days_ago": 45 },
    { "prop": P5, "sender": GOV,   "receiver": SURESH, "amount": 6500000,  "type": "REGISTER", "days_ago": 40 },
    { "prop": P6, "sender": GOV,   "receiver": KAVITA, "amount": 25000000, "type": "REGISTER", "days_ago": 35 },
    { "prop": P7, "sender": GOV,   "receiver": MOHAN,  "amount": 3800000,  "type": "REGISTER", "days_ago": 30 },
    { "prop": P8, "sender": GOV,   "receiver": LAKSHMI,"amount": 15000000, "type": "REGISTER", "days_ago": 25 },

    # Normal transfers
    { "prop": P5, "sender": SURESH, "receiver": VIJAY,  "amount": 6800000,  "type": "TRANSFER", "days_ago": 20 },
    { "prop": P8, "sender": LAKSHMI,"receiver": MEENA,  "amount": 15500000, "type": "TRANSFER", "days_ago": 18 },
]

for t in normal_txns:
    txn = models.Transaction(
        property_id        = t["prop"].property_id,
        sender_id          = t["sender"].user_id,
        receiver_id        = t["receiver"].user_id,
        amount             = t["amount"],
        payment_mode       = "ONLINE",
        transaction_type   = t["type"],
        blockchain_tx_hash = fake_tx_hash(f"{t['prop'].property_id}_{t['type']}"),
        is_on_chain        = True,
        timestamp          = ago(days=t["days_ago"]),
    )
    db.add(txn)

db.commit()
print(f"   ✅ {len(normal_txns)} normal transactions created")

# ─────────────────────────────────────────
# FRAUD PATTERN 1 — AMOUNT ANOMALY (DBSCAN)
# ─────────────────────────────────────────

print("\n🚨 Creating FRAUD PATTERN 1 — Amount Anomaly...")

# One suspiciously high transaction — 10x normal price
txn_anomaly = models.Transaction(
    property_id        = P6.property_id,
    sender_id          = KAVITA.user_id,
    receiver_id        = VIJAY.user_id,
    amount             = 250000000,   # ₹25 CRORE — statistical outlier
    payment_mode       = "ONLINE",
    transaction_type   = "TRANSFER",
    blockchain_tx_hash = fake_tx_hash("anomaly_001"),
    is_on_chain        = True,
    timestamp          = ago(days=10),
)
db.add(txn_anomaly)
db.commit()
print("   ✅ Anomaly transaction: ₹25 Crore (10x normal) — will trigger DBSCAN")

# ─────────────────────────────────────────
# FRAUD PATTERN 2 — CIRCULAR OWNERSHIP (LOUVAIN)
# P1: ARJUN → PRIYA → RAVI → ARJUN
# ─────────────────────────────────────────

print("\n🚨 Creating FRAUD PATTERN 2 — Circular Ownership...")

circular = [
    { "prop": P1, "sender": ARJUN, "receiver": PRIYA, "amount": 4600000, "days_ago": 22 },
    { "prop": P1, "sender": PRIYA, "receiver": RAVI,  "amount": 4700000, "days_ago": 20 },
    { "prop": P1, "sender": RAVI,  "receiver": ARJUN, "amount": 4800000, "days_ago": 18 },  # back to original!
]

for t in circular:
    txn = models.Transaction(
        property_id        = t["prop"].property_id,
        sender_id          = t["sender"].user_id,
        receiver_id        = t["receiver"].user_id,
        amount             = t["amount"],
        payment_mode       = "ONLINE",
        transaction_type   = "TRANSFER",
        blockchain_tx_hash = fake_tx_hash(f"circular_{t['sender'].user_id}_{t['receiver'].user_id}"),
        is_on_chain        = True,
        timestamp          = ago(days=t["days_ago"]),
    )
    db.add(txn)

# Update property owner back to ARJUN
P1.current_owner_id = ARJUN.user_id
db.commit()
print("   ✅ Circular chain: ARJUN→PRIYA→RAVI→ARJUN — will trigger Louvain")

# ─────────────────────────────────────────
# FRAUD PATTERN 3 — RAPID TRANSFER
# P3: Sold twice within 2 days
# ─────────────────────────────────────────

print("\n🚨 Creating FRAUD PATTERN 3 — Rapid Transfer...")

rapid = [
    { "prop": P3, "sender": RAVI,  "receiver": SURESH, "amount": 3300000, "days_ago": 14,    "hours": 0 },
    { "prop": P3, "sender": SURESH,"receiver": MEENA,  "amount": 3400000, "days_ago": 13,    "hours": 6 },  # only 30 hours later!
]

for t in rapid:
    txn = models.Transaction(
        property_id        = t["prop"].property_id,
        sender_id          = t["sender"].user_id,
        receiver_id        = t["receiver"].user_id,
        amount             = t["amount"],
        payment_mode       = "CASH",
        transaction_type   = "TRANSFER",
        blockchain_tx_hash = fake_tx_hash(f"rapid_{t['sender'].user_id}"),
        is_on_chain        = True,
        timestamp          = ago(days=t["days_ago"], hours=t["hours"]),
    )
    db.add(txn)

P3.current_owner_id = MEENA.user_id
db.commit()
print("   ✅ Rapid transfer: P3 sold twice in 30 hours — will trigger RAPID_TRANSFER")

# ─────────────────────────────────────────
# FRAUD PATTERN 4 — PRICE MANIPULATION
# P4: Price jumps from ₹8L to ₹40L in one transfer (5x)
# ─────────────────────────────────────────

print("\n🚨 Creating FRAUD PATTERN 4 — Price Manipulation...")

txn_price = models.Transaction(
    property_id        = P4.property_id,
    sender_id          = MEENA.user_id,
    receiver_id        = MOHAN.user_id,
    amount             = 40000000,   # was ₹80L, now ₹400L — 5x spike!
    payment_mode       = "CHEQUE",
    transaction_type   = "TRANSFER",
    blockchain_tx_hash = fake_tx_hash("price_manip_001"),
    is_on_chain        = True,
    timestamp          = ago(days=12),
)
db.add(txn_price)
P4.current_owner_id = MOHAN.user_id
P4.price = 40000000
db.commit()
print("   ✅ Price spike: ₹80L → ₹400L (5x) — will trigger PRICE_MANIPULATION")

# ─────────────────────────────────────────
# FRAUD PATTERN 5 — SELF DEALING
# ARJUN (user 3) transfers to ARJUN2 (user 11)
# Both have the SAME wallet address!
# ─────────────────────────────────────────

print("\n🚨 Creating FRAUD PATTERN 5 — Self Dealing...")

txn_self = models.Transaction(
    property_id        = P2.property_id,
    sender_id          = PRIYA.user_id,
    receiver_id        = ARJUN2.user_id,   # shell account
    amount             = 12500000,
    payment_mode       = "ONLINE",
    transaction_type   = "TRANSFER",
    blockchain_tx_hash = fake_tx_hash("self_deal_001"),
    is_on_chain        = True,
    timestamp          = ago(days=8),
)
db.add(txn_self)

# Also add a direct self transfer (same sender and receiver)
txn_self2 = models.Transaction(
    property_id        = P8.property_id,
    sender_id          = MEENA.user_id,
    receiver_id        = MEENA.user_id,   # sender == receiver!
    amount             = 500000,
    payment_mode       = "CASH",
    transaction_type   = "TRANSFER",
    blockchain_tx_hash = fake_tx_hash("self_deal_002"),
    is_on_chain        = False,
    timestamp          = ago(days=7),
)
db.add(txn_self2)
P2.current_owner_id = ARJUN2.user_id
db.commit()
print("   ✅ Shell account transfer + sender==receiver — will trigger SELF_DEALING")

# ─────────────────────────────────────────
# FRAUD PATTERN 6 — HIGH FREQUENCY PAIR
# SURESH and VIJAY transact 5 times
# ─────────────────────────────────────────

print("\n🚨 Creating FRAUD PATTERN 6 — High Frequency Pair...")

for i in range(5):
    txn_freq = models.Transaction(
        property_id        = P5.property_id,
        sender_id          = SURESH.user_id if i % 2 == 0 else VIJAY.user_id,
        receiver_id        = VIJAY.user_id  if i % 2 == 0 else SURESH.user_id,
        amount             = 100000 + (i * 50000),  # small varying amounts
        payment_mode       = "ONLINE",
        transaction_type   = "TRANSFER",
        blockchain_tx_hash = fake_tx_hash(f"high_freq_{i}"),
        is_on_chain        = True,
        timestamp          = ago(days=6-i, hours=i*3),
    )
    db.add(txn_freq)

db.commit()
print("   ✅ SURESH↔VIJAY transact 5 times — will trigger HIGH_FREQ_PAIR")

# ─────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────

total_users  = db.query(models.User).count()
total_props  = db.query(models.Property).count()
total_reqs   = db.query(models.PropertyRequest).count()
total_txns   = db.query(models.Transaction).count()

print("\n" + "─" * 50)
print("✅ SEEDING COMPLETE!")
print("─" * 50)
print(f"   👤 Users:               {total_users}")
print(f"   🏠 Properties:          {total_props}")
print(f"   📋 Property Requests:   {total_reqs}")
print(f"   💸 Transactions:        {total_txns}")
print("─" * 50)
print("\n📧 TEST LOGIN CREDENTIALS:")
print("─" * 50)
print("   ADMIN:      admin@blrs.com      / admin123")
print("   GOVERNMENT: gov@blrs.com        / gov123")
print("   OWNER 1:    arjun@test.com      / pass123")
print("   OWNER 2:    priya@test.com      / pass123")
print("   OWNER 3:    ravi@test.com       / pass123")
print("─" * 50)
print("\n🚨 FRAUD PATTERNS PLANTED:")
print("─" * 50)
print("   1. AMOUNT_ANOMALY     — P6: ₹25 Crore transaction (DBSCAN)")
print("   2. CIRCULAR_OWNERSHIP — P1: ARJUN→PRIYA→RAVI→ARJUN (Louvain)")
print("   3. RAPID_TRANSFER     — P3: Sold twice in 30 hours")
print("   4. PRICE_MANIPULATION — P4: ₹80L → ₹400L (5x spike)")
print("   5. SELF_DEALING       — P2: Same wallet + self transfer")
print("   6. HIGH_FREQ_PAIR     — P5: SURESH↔VIJAY 5 times")
print("─" * 50)
print("\n👉 Now go to Gov/Admin dashboard → Fraud Detection → Run Full Analysis")
print("   You should see all 6 signals fire!\n")

db.close()
