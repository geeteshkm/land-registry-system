"""
Fraud Detection Engine
======================
Signals detected:
  1. AMOUNT_ANOMALY     — DBSCAN outlier on transaction amount
  2. CIRCULAR_OWNERSHIP — Louvain community with high internal edge density
  3. RAPID_TRANSFER     — same property transferred multiple times within 7 days
  4. PRICE_MANIPULATION — same property price changes > 200% in one transfer
  5. SELF_DEALING       — sender and receiver share same wallet or are linked
  6. HIGH_FREQ_PAIR     — same two users transact > 3 times
"""

import pandas as pd
import numpy as np
import networkx as nx
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import List, Dict, Any
try:
    from . import models
except ImportError:
    import models

# ─────────────────────────────────────────
# THRESHOLDS  (tune as needed)
# ─────────────────────────────────────────

DBSCAN_EPS          = 0.8    # after StandardScaler normalization
DBSCAN_MIN_SAMPLES  = 2
RAPID_DAYS          = 7      # property flipped within N days
PRICE_SPIKE_RATIO   = 2.0    # price increased by 200%+
HIGH_FREQ_THRESHOLD = 3      # same pair transacts more than N times
HIGH_FREQ_MIN_PROPERTIES = 3
HIGH_FREQ_MAX_SPAN_DAYS = 120
HIGH_FREQ_MAX_MEDIAN_GAP_DAYS = 45
COMMUNITY_DENSITY   = 1.0    # internal_edges >= members count


# ─────────────────────────────────────────
# MAIN ENTRY
# ─────────────────────────────────────────

def run_fraud_analysis(db: Session) -> Dict[str, Any]:

    transactions = db.query(models.Transaction).all()

    if not transactions:
        return {
            "total_transactions":    0,
            "total_alerts":          0,
            "amount_anomalies":      [],
            "circular_ownership":    [],
            "rapid_transfers":       [],
            "price_manipulations":   [],
            "self_dealing":          [],
            "high_freq_pairs":       [],
            "summary":               {},
        }

    # Build DataFrame
    rows = []
    for t in transactions:
        rows.append({
            "transaction_id": t.transaction_id,
            "property_id":    t.property_id,
            "sender_id":      t.sender_id,
            "receiver_id":    t.receiver_id,
            "amount":         float(t.amount),
            "timestamp":      t.timestamp,
        })

    df = pd.DataFrame(rows)

    results = {
        "total_transactions":  len(df),
        "amount_anomalies":    _detect_amount_anomalies(df),
        "circular_ownership":  _detect_circular_ownership(df),
        "rapid_transfers":     _detect_rapid_transfers(df),
        "price_manipulations": _detect_price_manipulation(df),
        "self_dealing":        _detect_self_dealing(df, db),
        "high_freq_pairs":     _detect_high_freq_pairs(df),
    }

    # Persist new alerts to DB
    total_new = _persist_alerts(results, db)

    results["total_alerts"] = total_new
    results["summary"] = _build_summary(results)

    return results


# ─────────────────────────────────────────
# SIGNAL 1 — AMOUNT ANOMALY (DBSCAN)
# ─────────────────────────────────────────

def _detect_amount_anomalies(df: pd.DataFrame) -> List[Dict]:
    if len(df) < DBSCAN_MIN_SAMPLES:
        return []

    amounts = np.log1p(df["amount"].values).reshape(-1, 1)
    scaled  = StandardScaler().fit_transform(amounts)

    labels  = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES).fit_predict(scaled)
    df      = df.copy()
    df["cluster"]       = labels
    df["scaled_amount"] = scaled.flatten()

    mean_scaled = scaled[labels != -1].mean() if (labels != -1).any() else 0
    anomalies   = df[df["cluster"] == -1].copy()

    results = []
    for _, row in anomalies.iterrows():
        # Distance from the cluster mean — farther = higher risk
        distance   = abs(row["scaled_amount"] - mean_scaled)
        # Cap at 99, minimum 65
        risk_score = min(99.0, round(65 + (distance * 10), 1))
        results.append({
            "transaction_id": int(row["transaction_id"]),
            "property_id":    int(row["property_id"]),
            "sender_id":      int(row["sender_id"]),
            "receiver_id":    int(row["receiver_id"]),
            "amount":         row["amount"],
            "risk_score":     risk_score,
            "reason":         f"Transaction amount ₹{int(row['amount']):,} is a statistical outlier (distance: {round(distance,2)} std devs) — Risk: {risk_score}/100",
        })

    return results


# ─────────────────────────────────────────
# SIGNAL 2 — CIRCULAR OWNERSHIP (LOUVAIN)
# ─────────────────────────────────────────

def _detect_circular_ownership(df: pd.DataFrame) -> List[Dict]:
    suspicious = []
    for property_id, group in df.groupby("property_id"):
        ordered = group.sort_values("timestamp").reset_index(drop=True)
        if len(ordered) < 3:
            continue

        for idx in range(2, len(ordered)):
            tx_a = ordered.iloc[idx - 2]
            tx_b = ordered.iloc[idx - 1]
            tx_c = ordered.iloc[idx]

            members = [
                int(tx_a["sender_id"]),
                int(tx_a["receiver_id"]),
                int(tx_b["receiver_id"]),
            ]
            if len(set(members)) < 3:
                continue

            is_closed_cycle = (
                int(tx_b["sender_id"]) == int(tx_a["receiver_id"])
                and int(tx_c["sender_id"]) == int(tx_b["receiver_id"])
                and int(tx_c["receiver_id"]) == int(tx_a["sender_id"])
            )
            if not is_closed_cycle:
                continue

            cycle_transaction_ids = [
                int(tx_a["transaction_id"]),
                int(tx_b["transaction_id"]),
                int(tx_c["transaction_id"]),
            ]
            suspicious.append({
                "property_id": property_id,
                "members": sorted(set(members)),
                "transaction_ids": cycle_transaction_ids,
                "cycle_edges": [
                    (int(tx_a["sender_id"]), int(tx_a["receiver_id"])),
                    (int(tx_b["sender_id"]), int(tx_b["receiver_id"])),
                    (int(tx_c["sender_id"]), int(tx_c["receiver_id"])),
                ],
                "risk_score": 92.0,
                "reason": "Same property returned to a prior owner through a 3-step ownership loop",
            })

    return suspicious


# ─────────────────────────────────────────
# SIGNAL 3 — RAPID TRANSFER
# ─────────────────────────────────────────

def _detect_rapid_transfers(df: pd.DataFrame) -> List[Dict]:
    flagged = []
    cutoff  = timedelta(days=RAPID_DAYS)

    for prop_id, group in df.groupby("property_id"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        for i in range(1, len(group)):
            delta = group.loc[i, "timestamp"] - group.loc[i - 1, "timestamp"]
            if delta < cutoff:

                # ── Dynamic risk score — faster = higher risk ──
                hours_elapsed = delta.total_seconds() / 3600
                if hours_elapsed < 1:
                    risk_score = 99.0   # within 1 hour — critical
                elif hours_elapsed < 24:
                    risk_score = 92.0   # within same day
                elif hours_elapsed < 48:
                    risk_score = 85.0   # within 2 days
                elif hours_elapsed < 72:
                    risk_score = 78.0   # within 3 days
                else:
                    # 3-7 days: scale from 65 to 75
                    risk_score = round(75 - ((hours_elapsed - 72) / (RAPID_DAYS * 24 - 72)) * 10, 1)

                flagged.append({
                    "property_id":    int(prop_id),
                    "transaction_id": int(group.loc[i, "transaction_id"]),
                    "sender_id":      int(group.loc[i, "sender_id"]),
                    "receiver_id":    int(group.loc[i, "receiver_id"]),
                    "days_since_last_transfer": delta.days,
                    "hours_since_last_transfer": round(hours_elapsed, 1),
                    "risk_score":     risk_score,
                    "reason":         f"Property transferred again after only {round(hours_elapsed,1)} hours — Risk: {risk_score}/100",
                })

    return flagged


# ─────────────────────────────────────────
# SIGNAL 4 — PRICE MANIPULATION
# ─────────────────────────────────────────

def _detect_price_manipulation(df: pd.DataFrame) -> List[Dict]:
    flagged = []

    for prop_id, group in df.groupby("property_id"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        for i in range(1, len(group)):
            prev_price = group.loc[i - 1, "amount"]
            curr_price = group.loc[i,     "amount"]
            if prev_price == 0:
                continue
            ratio = curr_price / prev_price
            if ratio >= PRICE_SPIKE_RATIO or ratio <= (1 / PRICE_SPIKE_RATIO):

                # ── Dynamic risk score based on how extreme the change is ──
                # Use the deviation from 1.0 (no change) to measure severity
                deviation = max(ratio, 1 / ratio)  # always >= 1

                if deviation >= 10.0:
                    risk_score = 99.0   # 10x or more → critical
                elif deviation >= 5.0:
                    risk_score = 95.0   # 5x → very high
                elif deviation >= 3.0:
                    risk_score = 88.0   # 3x → high
                elif deviation >= 2.0:
                    risk_score = 75.0   # 2x → medium-high
                else:
                    # Between PRICE_SPIKE_RATIO (2.0) and 2.0
                    # Scale linearly from 50 to 75
                    risk_score = round(50 + (deviation - 1.0) * 25, 1)

                # Direction label
                if ratio >= PRICE_SPIKE_RATIO:
                    direction = f"increased {round((ratio - 1) * 100, 1)}%"
                else:
                    direction = f"decreased {round((1 - ratio) * 100, 1)}%"

                flagged.append({
                    "property_id":    int(prop_id),
                    "transaction_id": int(group.loc[i, "transaction_id"]),
                    "sender_id":      int(group.loc[i, "sender_id"]),
                    "receiver_id":    int(group.loc[i, "receiver_id"]),
                    "previous_price": prev_price,
                    "current_price":  curr_price,
                    "ratio":          round(ratio, 2),
                    "risk_score":     risk_score,
                    "reason":         f"Price {direction} in one transfer (ratio: {round(ratio,2)}x) — Risk: {risk_score}/100",
                })

    return flagged


# ─────────────────────────────────────────
# SIGNAL 5 — SELF DEALING
# ─────────────────────────────────────────

def _detect_self_dealing(df: pd.DataFrame, db: Session) -> List[Dict]:
    """Flags transactions where sender == receiver (same user_id or same wallet)."""
    flagged = []

    # Same user_id
    same_id = df[df["sender_id"] == df["receiver_id"]]
    for _, row in same_id.iterrows():
        flagged.append({
            "transaction_id": int(row["transaction_id"]),
            "property_id":    int(row["property_id"]),
            "user_id":        int(row["sender_id"]),
            "risk_score":     90.0,
            "reason":         "Sender and receiver are the same user (self-dealing)",
        })

    # Same wallet address (different user_id but same wallet)
    users = db.query(models.User).all()
    wallet_map = {u.user_id: u.wallet_address.lower() for u in users}

    for _, row in df.iterrows():
        s_wallet = wallet_map.get(int(row["sender_id"]), "")
        r_wallet = wallet_map.get(int(row["receiver_id"]), "")
        if s_wallet and r_wallet and s_wallet == r_wallet and int(row["sender_id"]) != int(row["receiver_id"]):
            flagged.append({
                "transaction_id": int(row["transaction_id"]),
                "property_id":    int(row["property_id"]),
                "sender_id":      int(row["sender_id"]),
                "receiver_id":    int(row["receiver_id"]),
                "wallet":         s_wallet,
                "risk_score":     95.0,
                "reason":         "Different user IDs but same wallet address (shell account)",
            })

    return flagged


# ─────────────────────────────────────────
# SIGNAL 6 — HIGH FREQUENCY PAIR
# ─────────────────────────────────────────

def _detect_high_freq_pairs(df: pd.DataFrame) -> List[Dict]:
    flagged = []
    for (sender, receiver), group in df.groupby(["sender_id", "receiver_id"]):
        if int(sender) == 1 or int(receiver) == 1:
            continue
        ordered = group.sort_values("timestamp").reset_index(drop=True)
        count = len(ordered)
        if count <= HIGH_FREQ_THRESHOLD:
            continue

        distinct_properties = int(ordered["property_id"].nunique())
        if distinct_properties < HIGH_FREQ_MIN_PROPERTIES:
            continue

        span_days = max(
            (ordered.iloc[-1]["timestamp"] - ordered.iloc[0]["timestamp"]).total_seconds() / 86400,
            0.0,
        )
        if span_days > HIGH_FREQ_MAX_SPAN_DAYS:
            continue

        gaps = ordered["timestamp"].diff().dropna().dt.total_seconds() / 86400
        median_gap_days = float(gaps.median()) if not gaps.empty else span_days
        if median_gap_days > HIGH_FREQ_MAX_MEDIAN_GAP_DAYS:
            continue

        urgency_bonus = max(0.0, (HIGH_FREQ_MAX_MEDIAN_GAP_DAYS - median_gap_days) * 0.35)
        breadth_bonus = max(0, distinct_properties - HIGH_FREQ_MIN_PROPERTIES) * 3.0
        risk_score = min(92.0, round(62.0 + urgency_bonus + breadth_bonus, 1))

        flagged.append({
            "sender_id": sender,
            "receiver_id": receiver,
            "transaction_count": count,
            "distinct_properties": distinct_properties,
            "span_days": round(span_days, 1),
            "median_gap_days": round(median_gap_days, 1),
            "transaction_ids": [int(tx_id) for tx_id in ordered["transaction_id"].tolist()],
            "risk_score": risk_score,
            "reason": (
                f"Same pair transacted {count} times across {distinct_properties} properties "
                f"within {round(span_days,1)} days (median gap {round(median_gap_days,1)} days)"
            ),
        })

    return flagged


# ─────────────────────────────────────────
# PERSIST ALERTS TO DB
# ─────────────────────────────────────────

def _persist_alerts(results: Dict, db: Session) -> int:
    """Save new fraud alerts to DB, skip duplicates."""
    new_count = 0

    def _save(transaction_id, property_id, user_id, fraud_type, risk_score, description):
        nonlocal new_count
        # Skip if already exists
        existing = db.query(models.FraudAlert).filter(
            models.FraudAlert.transaction_id == transaction_id,
            models.FraudAlert.fraud_type     == fraud_type,
        ).first()
        if existing:
            return
        alert = models.FraudAlert(
            transaction_id  = transaction_id,
            property_id     = property_id,
            flagged_user_id = user_id,
            fraud_type      = fraud_type,
            risk_score      = risk_score,
            description     = description,
        )
        db.add(alert)
        new_count += 1

    for item in results.get("amount_anomalies", []):
        _save(item["transaction_id"], item["property_id"], item["sender_id"],
              "AMOUNT_ANOMALY", item["risk_score"], item["reason"])

    for item in results.get("rapid_transfers", []):
        _save(item["transaction_id"], item["property_id"], item["sender_id"],
              "RAPID_TRANSFER", item["risk_score"], item["reason"])

    for item in results.get("price_manipulations", []):
        _save(item["transaction_id"], item["property_id"], item["sender_id"],
              "PRICE_MANIPULATION", item["risk_score"], item["reason"])

    for item in results.get("self_dealing", []):
        _save(item.get("transaction_id"), item.get("property_id"),
              item.get("user_id") or item.get("sender_id"),
              "SELF_DEALING", item["risk_score"], item["reason"])

    for item in results.get("high_freq_pairs", []):
        _save(None, None, item["sender_id"],
              "HIGH_FREQ_PAIR", item["risk_score"], item["reason"])

    # Circular ownership — no single transaction_id
    for item in results.get("circular_ownership", []):
        for member in item["members"]:
            _save(None, None, member,
                  "CIRCULAR_OWNERSHIP", item["risk_score"], item["reason"])

    db.commit()
    return new_count


# ─────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────

def _build_summary(results: Dict) -> Dict:
    return {
        "amount_anomalies":    len(results["amount_anomalies"]),
        "circular_ownership":  len(results["circular_ownership"]),
        "rapid_transfers":     len(results["rapid_transfers"]),
        "price_manipulations": len(results["price_manipulations"]),
        "self_dealing":        len(results["self_dealing"]),
        "high_freq_pairs":     len(results["high_freq_pairs"]),
        "total_signals":       sum([
            len(results["amount_anomalies"]),
            len(results["circular_ownership"]),
            len(results["rapid_transfers"]),
            len(results["price_manipulations"]),
            len(results["self_dealing"]),
            len(results["high_freq_pairs"]),
        ]),
    }
