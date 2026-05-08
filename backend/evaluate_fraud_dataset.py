"""
Synthetic fraud dataset generator and evaluator.

What this script does:
1. Generates a reproducible 500-transaction synthetic dataset.
2. Plants 63 labeled fraudulent transactions across the six implemented signals.
3. Splits the dataset 70/15/15 with stratification.
4. Evaluates the current rule-based detector offline.
5. Runs Isolation Forest and LOF baselines on the same features.
6. Writes CSV/JSON artifacts under backend/artifacts/.

Run:
    python evaluate_fraud_dataset.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler


SEED = 42
TOTAL_TRANSACTIONS = 500
TOTAL_FRAUDULENT = 63

DBSCAN_EPS = 0.8
DBSCAN_MIN_SAMPLES = 2
RAPID_DAYS = 7
PRICE_SPIKE_RATIO = 2.0
HIGH_FREQ_THRESHOLD = 3
HIGH_FREQ_MIN_PROPERTIES = 3
HIGH_FREQ_MAX_SPAN_DAYS = 120
HIGH_FREQ_MAX_MEDIAN_GAP_DAYS = 45
COMMUNITY_DENSITY = 1.0

SIGNAL_WEIGHTS = {
    "AMOUNT_ANOMALY": 0.72,
    "CIRCULAR_OWNERSHIP": 0.82,
    "RAPID_TRANSFER": 0.80,
    "PRICE_MANIPULATION": 0.86,
    "SELF_DEALING": 0.94,
    "HIGH_FREQ_PAIR": 0.80,
}
COMBINATION_BONUS = 0.08
WEIGHT_SEARCH_ITERATIONS = 400

SIGNAL_VARIANTS = {
    "DBSCAN Only": ["AMOUNT_ANOMALY"],
    "Louvain Only": ["CIRCULAR_OWNERSHIP"],
    "Rule-Based": ["RAPID_TRANSFER", "PRICE_MANIPULATION", "SELF_DEALING", "HIGH_FREQ_PAIR"],
    "Rules + DBSCAN": ["AMOUNT_ANOMALY", "RAPID_TRANSFER", "PRICE_MANIPULATION", "SELF_DEALING", "HIGH_FREQ_PAIR"],
    "Rules + Louvain": ["CIRCULAR_OWNERSHIP", "RAPID_TRANSFER", "PRICE_MANIPULATION", "SELF_DEALING", "HIGH_FREQ_PAIR"],
    "Proposed (All)": [
        "AMOUNT_ANOMALY",
        "CIRCULAR_OWNERSHIP",
        "RAPID_TRANSFER",
        "PRICE_MANIPULATION",
        "SELF_DEALING",
        "HIGH_FREQ_PAIR",
    ],
}

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


@dataclass
class User:
    user_id: int
    wallet_address: str


@dataclass
class PropertyState:
    property_id: int
    current_owner_id: int
    last_amount: float
    last_timestamp: datetime
    owner_history: List[int]


def rng() -> np.random.Generator:
    return np.random.default_rng(SEED)


def wallet_for(seed_value: int) -> str:
    base = f"{seed_value:040x}"
    return f"0x{base[-40:]}"


def generate_users() -> Tuple[List[User], Dict[int, str], List[Tuple[int, int]]]:
    users = [User(user_id=1, wallet_address=wallet_for(1))]
    shell_pairs: List[Tuple[int, int]] = []

    for user_id in range(2, 92):
        users.append(User(user_id=user_id, wallet_address=wallet_for(user_id)))

    # Create six shell-account pairs that share wallets.
    pair_sources = [(2, 82), (3, 83), (4, 84), (5, 85), (6, 86), (7, 87)]
    wallet_map = {user.user_id: user.wallet_address for user in users}
    for primary_id, shell_id in pair_sources:
        wallet_map[shell_id] = wallet_map[primary_id]
        shell_pairs.append((primary_id, shell_id))

    return users, wallet_map, shell_pairs


def initialize_properties(
    generator: np.random.Generator,
    owner_ids: List[int],
) -> Dict[int, PropertyState]:
    base_time = datetime(2025, 1, 1, 9, 0, 0)
    properties: Dict[int, PropertyState] = {}
    for property_id in range(1, 121):
        owner_id = int(generator.choice(owner_ids))
        amount = float(np.round(generator.normal(6_000_000, 1_500_000)))
        amount = max(amount, 1_500_000.0)
        created_at = base_time + timedelta(hours=property_id * 6)
        properties[property_id] = PropertyState(
            property_id=property_id,
            current_owner_id=owner_id,
            last_amount=amount,
            last_timestamp=created_at,
            owner_history=[owner_id],
        )
    return properties


def make_transaction(
    tx_id: int,
    property_id: int,
    sender_id: int,
    receiver_id: int,
    amount: float,
    timestamp: datetime,
    label: int,
    planted_signal: str,
) -> Dict[str, Any]:
    return {
        "transaction_id": tx_id,
        "property_id": property_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "amount": float(amount),
        "timestamp": timestamp,
        "label": int(label),
        "planted_signal": planted_signal,
    }


def build_generation_notes() -> Dict[str, Any]:
    return {
        "normal_behavior": {
            "properties_used": "normal-only pool plus 8 rapid-transfer support properties and a small edge-case normal pool",
            "gap_days_range": [30, 120],
            "price_ratio_range": [0.95, 1.12],
            "guardrails": [
                "Avoid repeat directed pairs above 2 for normal traffic",
                "Avoid sending a property back to any of its 3 most recent owners in normal traffic",
                "Keep shell-account wallets out of normal transfers",
                "Reserve dedicated properties for planted fraud scenarios",
                "Inject a few documented borderline-but-legitimate transactions to prevent unrealistically perfect separation",
            ],
        },
        "fraud_blueprint": {
            "rapid_transfer": 8,
            "amount_anomaly": 1,
            "price_manipulation": 10,
            "self_dealing": 19,
            "circular_ownership": 9,
            "high_freq_pair": 16,
        },
        "reserved_property_ranges": {
            "rapid_transfer": "1-8",
            "amount_anomaly": "9",
            "price_manipulation": "17-26",
            "self_dealing": "27-38, 59-65",
            "circular_ownership": "40-42",
            "high_freq_pair": "43-58",
            "normal_only": "10-16, 66-120",
            "edge_case_normals": "66-72",
        },
    }


def generate_dataset() -> pd.DataFrame:
    generator = rng()
    _, wallet_map, shell_pairs = generate_users()

    owner_ids = list(range(2, 92))
    properties = initialize_properties(generator, owner_ids)
    all_transactions: List[Dict[str, Any]] = []
    tx_id = 1
    shell_user_ids = {shell_id for _, shell_id in shell_pairs}
    primary_shell_ids = {primary_id for primary_id, _ in shell_pairs}
    shell_related_ids = shell_user_ids | primary_shell_ids

    rapid_property_ids = list(range(1, 9))
    amount_property_ids = [9]
    price_property_ids = list(range(17, 27))
    self_dealing_property_ids = list(range(27, 39)) + list(range(59, 66))
    circular_property_ids = [40, 41, 42]
    high_freq_property_ids = list(range(43, 59))
    reserved_fraud_properties = set(
        rapid_property_ids
        + amount_property_ids
        + price_property_ids
        + self_dealing_property_ids
        + circular_property_ids
        + high_freq_property_ids
    )
    normal_only_properties = [
        property_id for property_id in properties.keys()
        if property_id not in reserved_fraud_properties
    ]
    edge_case_normal_properties = [66, 67, 68, 69, 70, 71, 72]
    clean_normal_properties = [
        property_id for property_id in normal_only_properties
        if property_id not in edge_case_normal_properties
    ]
    normal_pair_counts: Dict[Tuple[int, int], int] = defaultdict(int)

    def add_tx(
        property_id: int,
        sender_id: int,
        receiver_id: int,
        amount: float,
        timestamp: datetime,
        label: int,
        planted_signal: str,
        update_owner: bool = True,
    ) -> None:
        nonlocal tx_id
        all_transactions.append(
            make_transaction(
                tx_id=tx_id,
                property_id=property_id,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                timestamp=timestamp,
                label=label,
                planted_signal=planted_signal,
            )
        )
        state = properties[property_id]
        state.last_amount = float(amount)
        state.last_timestamp = timestamp
        if update_owner:
            state.current_owner_id = receiver_id
            if not state.owner_history or state.owner_history[-1] != receiver_id:
                state.owner_history.append(receiver_id)
        tx_id += 1

    # 120 initial registrations from government to first owner.
    for property_id, state in properties.items():
        add_tx(
            property_id=property_id,
            sender_id=1,
            receiver_id=state.current_owner_id,
            amount=state.last_amount,
            timestamp=state.last_timestamp,
            label=0,
            planted_signal="NORMAL",
        )

    def choose_normal_receiver(state: PropertyState, sender_id: int) -> int:
        recent_owners = set(state.owner_history[-3:])
        candidates = [
            uid for uid in owner_ids
            if uid != sender_id
            and uid not in recent_owners
            and uid not in shell_related_ids
            and normal_pair_counts[(sender_id, uid)] < 2
        ]
        if not candidates:
            candidates = [
                uid for uid in owner_ids
                if uid != sender_id
                and uid not in recent_owners
                and uid not in shell_related_ids
            ]
        if not candidates:
            candidates = [
                uid for uid in owner_ids
                if uid != sender_id and uid not in shell_related_ids
            ]
        return int(generator.choice(candidates))

    # 295 clean normal transfers on dedicated non-fraud properties.
    for _ in range(295):
        property_id = int(generator.choice(clean_normal_properties))
        state = properties[property_id]
        sender_id = state.current_owner_id
        receiver_id = choose_normal_receiver(state, sender_id)
        price_ratio = float(np.clip(generator.normal(1.02, 0.035), 0.95, 1.12))
        amount = max(2_000_000.0, state.last_amount * price_ratio)
        timestamp = state.last_timestamp + timedelta(days=int(generator.integers(30, 121)))
        add_tx(
            property_id=property_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            amount=round(amount, 2),
            timestamp=timestamp,
            label=0,
            planted_signal="NORMAL",
        )
        normal_pair_counts[(sender_id, receiver_id)] += 1

    # 5 legitimate-but-risky edge cases to keep the benchmark realistic.
    # These are intentionally close to fraud heuristics while still labeled normal.
    edge_case_specs = [
        {"property_id": 66, "kind": "PRICE"},
        {"property_id": 67, "kind": "PRICE"},
        {"property_id": 68, "kind": "PAIR"},
        {"property_id": 69, "kind": "PAIR"},
        {"property_id": 70, "kind": "RAPID"},
        {"property_id": 71, "kind": "PRICE"},
        {"property_id": 72, "kind": "PRICE"},
    ]
    for spec in edge_case_specs:
        property_id = spec["property_id"]
        state = properties[property_id]
        sender_id = state.current_owner_id

        if spec["kind"] == "PRICE":
            receiver_id = choose_normal_receiver(state, sender_id)
            amount = round(state.last_amount * float(generator.uniform(2.05, 2.25)), 2)
            timestamp = state.last_timestamp + timedelta(days=58)
            add_tx(
                property_id=property_id,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                timestamp=timestamp,
                label=0,
                planted_signal="NORMAL",
            )
            normal_pair_counts[(sender_id, receiver_id)] += 1

        elif spec["kind"] == "PAIR":
            receiver_id = sender_id + 20 if sender_id + 20 <= 91 else sender_id - 10
            if receiver_id in shell_related_ids or receiver_id == sender_id:
                receiver_id = choose_normal_receiver(state, sender_id)
            for repeat_index in range(4):
                timestamp = state.last_timestamp + timedelta(days=35 + repeat_index * 8)
                amount = round(state.last_amount * (1.01 + repeat_index * 0.01), 2)
                add_tx(
                    property_id=property_id,
                    sender_id=sender_id,
                    receiver_id=receiver_id,
                    amount=amount,
                    timestamp=timestamp,
                    label=0,
                    planted_signal="NORMAL",
                )
                normal_pair_counts[(sender_id, receiver_id)] += 1
                state.current_owner_id = sender_id
                state.owner_history = [sender_id]

        elif spec["kind"] == "RAPID":
            mid_owner = choose_normal_receiver(state, sender_id)
            rapid_time = state.last_timestamp + timedelta(days=40)
            add_tx(
                property_id=property_id,
                sender_id=sender_id,
                receiver_id=mid_owner,
                amount=round(state.last_amount * 1.01, 2),
                timestamp=rapid_time,
                label=0,
                planted_signal="NORMAL",
            )
            normal_pair_counts[(sender_id, mid_owner)] += 1

            final_owner = choose_normal_receiver(state, mid_owner)
            add_tx(
                property_id=property_id,
                sender_id=mid_owner,
                receiver_id=final_owner,
                amount=round(state.last_amount * 1.02, 2),
                timestamp=rapid_time + timedelta(days=4),
                label=0,
                planted_signal="NORMAL",
            )
            normal_pair_counts[(mid_owner, final_owner)] += 1

    # 8 rapid-transfer support transactions (normal) + 8 labeled rapid frauds.
    for property_id in rapid_property_ids:
        state = properties[property_id]
        sender_id = state.current_owner_id
        mid_owner = int(generator.choice([
            uid for uid in owner_ids if uid != sender_id and uid not in shell_related_ids
        ]))
        support_time = state.last_timestamp + timedelta(days=42)
        support_amount = round(state.last_amount * 1.02, 2)
        add_tx(
            property_id=property_id,
            sender_id=sender_id,
            receiver_id=mid_owner,
            amount=support_amount,
            timestamp=support_time,
            label=0,
            planted_signal="NORMAL",
        )
        normal_pair_counts[(sender_id, mid_owner)] += 1

        final_owner = int(generator.choice([
            uid for uid in owner_ids if uid not in (sender_id, mid_owner) and uid not in shell_related_ids
        ]))
        fraud_time = support_time + timedelta(hours=12)
        fraud_amount = round(support_amount * 1.015, 2)
        add_tx(
            property_id=property_id,
            sender_id=mid_owner,
            receiver_id=final_owner,
            amount=fraud_amount,
            timestamp=fraud_time,
            label=1,
            planted_signal="RAPID_TRANSFER",
        )

    # 1 extreme amount anomaly.
    state = properties[9]
    sender_id = state.current_owner_id
    receiver_id = int(generator.choice([uid for uid in owner_ids if uid != sender_id and uid not in shell_related_ids]))
    timestamp = state.last_timestamp + timedelta(days=55)
    add_tx(
        property_id=9,
        sender_id=sender_id,
        receiver_id=receiver_id,
        amount=round(state.last_amount * 38.0, 2),
        timestamp=timestamp,
        label=1,
        planted_signal="AMOUNT_ANOMALY",
    )

    # 10 price manipulations.
    for property_id in price_property_ids:
        state = properties[property_id]
        sender_id = state.current_owner_id
        receiver_id = int(generator.choice([uid for uid in owner_ids if uid != sender_id and uid not in shell_related_ids]))
        timestamp = state.last_timestamp + timedelta(days=60)
        amount = round(state.last_amount * float(generator.uniform(2.8, 4.5)), 2)
        add_tx(
            property_id=property_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            amount=amount,
            timestamp=timestamp,
            label=1,
            planted_signal="PRICE_MANIPULATION",
        )

    # 19 self-dealing transactions: six same-wallet shell transfers and thirteen same-user transfers.
    for index, (primary_id, shell_id) in enumerate(shell_pairs):
        property_id = 26 + index + 1
        state = properties[property_id]
        if state.current_owner_id != primary_id:
            state.current_owner_id = primary_id
            state.owner_history = [primary_id]
        timestamp = state.last_timestamp + timedelta(days=22)
        amount = round(state.last_amount * 1.04, 2)
        add_tx(
            property_id=property_id,
            sender_id=primary_id,
            receiver_id=shell_id,
            amount=amount,
            timestamp=timestamp,
            label=1,
            planted_signal="SELF_DEALING",
        )

    for property_id in range(33, 39):
        state = properties[property_id]
        sender_id = state.current_owner_id
        timestamp = state.last_timestamp + timedelta(days=24)
        amount = round(state.last_amount * 0.98, 2)
        add_tx(
            property_id=property_id,
            sender_id=sender_id,
            receiver_id=sender_id,
            amount=amount,
            timestamp=timestamp,
            label=1,
            planted_signal="SELF_DEALING",
            update_owner=False,
        )

    for property_id in range(59, 66):
        state = properties[property_id]
        sender_id = state.current_owner_id
        timestamp = state.last_timestamp + timedelta(days=26)
        amount = round(state.last_amount * 1.01, 2)
        add_tx(
            property_id=property_id,
            sender_id=sender_id,
            receiver_id=sender_id,
            amount=amount,
            timestamp=timestamp,
            label=1,
            planted_signal="SELF_DEALING",
            update_owner=False,
        )

    # 9 circular-ownership transactions as three 3-edge cycles.
    circular_groups = [(40, [10, 11, 12]), (41, [13, 14, 15]), (42, [16, 17, 18])]
    for property_id, members in circular_groups:
        state = properties[property_id]
        state.current_owner_id = members[0]
        state.owner_history = [members[0]]
        base_amount = state.last_amount
        base_time = state.last_timestamp + timedelta(days=70)
        edges = [(members[0], members[1]), (members[1], members[2]), (members[2], members[0])]
        for edge_index, (sender_id, receiver_id) in enumerate(edges):
            add_tx(
                property_id=property_id,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=round(base_amount * (1.01 + edge_index * 0.01), 2),
                timestamp=base_time + timedelta(days=edge_index * 5),
                label=1,
                planted_signal="CIRCULAR_OWNERSHIP",
            )

    # 16 high-frequency-pair transactions as four repeated directed pairs.
    repeated_pairs = [(19, 20), (21, 22), (23, 24), (25, 26)]
    pair_properties = [(43, 44, 45, 46), (47, 48, 49, 50), (51, 52, 53, 54), (55, 56, 57, 58)]
    for (sender_id, receiver_id), property_group in zip(repeated_pairs, pair_properties):
        for offset, property_id in enumerate(property_group):
            state = properties[property_id]
            state.current_owner_id = sender_id
            state.owner_history = [sender_id]
            add_tx(
                property_id=property_id,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=round(state.last_amount * (1.02 + offset * 0.01), 2),
                timestamp=state.last_timestamp + timedelta(days=45 + offset * 7),
                label=1,
                planted_signal="HIGH_FREQ_PAIR",
            )

    df = pd.DataFrame(all_transactions).sort_values("timestamp").reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    if len(df) != TOTAL_TRANSACTIONS:
        raise RuntimeError(f"Expected {TOTAL_TRANSACTIONS} transactions, found {len(df)}")
    if int(df["label"].sum()) != TOTAL_FRAUDULENT:
        raise RuntimeError(f"Expected {TOTAL_FRAUDULENT} fraud labels, found {int(df['label'].sum())}")

    # Attach wallet data for feature engineering and self-dealing checks.
    df["sender_wallet"] = df["sender_id"].map(wallet_map)
    df["receiver_wallet"] = df["receiver_id"].map(wallet_map)
    df.attrs["generation_notes"] = build_generation_notes()
    return df


def apply_splits(df: pd.DataFrame) -> pd.DataFrame:
    train_val_idx, test_idx = train_test_split(
        df.index,
        test_size=0.15,
        random_state=SEED,
        stratify=df["label"],
    )

    train_idx, val_idx = train_test_split(
        train_val_idx,
        test_size=(0.15 / 0.85),
        random_state=SEED,
        stratify=df.loc[train_val_idx, "label"],
    )

    split_series = pd.Series(index=df.index, dtype="object")
    split_series.loc[train_idx] = "train"
    split_series.loc[val_idx] = "validation"
    split_series.loc[test_idx] = "test"
    df = df.copy()
    df["split"] = split_series
    return df


def detect_rule_signals(df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "amount_anomalies": detect_amount_anomalies(df),
        "circular_ownership": detect_circular_ownership(df),
        "rapid_transfers": detect_rapid_transfers(df),
        "price_manipulations": detect_price_manipulation(df),
        "self_dealing": detect_self_dealing(df),
        "high_freq_pairs": detect_high_freq_pairs(df),
    }


def detect_amount_anomalies(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if len(df) < DBSCAN_MIN_SAMPLES:
        return []

    amounts = np.log1p(df["amount"].astype(float).values).reshape(-1, 1)
    scaled = StandardScaler().fit_transform(amounts)
    labels = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES).fit_predict(scaled)
    mean_scaled = scaled[labels != -1].mean() if (labels != -1).any() else 0.0
    working = df.copy()
    working["cluster"] = labels
    working["scaled_amount"] = scaled.flatten()

    results = []
    for _, row in working[working["cluster"] == -1].iterrows():
        distance = abs(float(row["scaled_amount"]) - float(mean_scaled))
        risk_score = min(99.0, round(65 + distance * 10, 1))
        results.append(
            {
                "transaction_id": int(row["transaction_id"]),
                "risk_score": risk_score,
                "reason": "DBSCAN amount outlier",
            }
        )
    return results


def detect_circular_ownership(df: pd.DataFrame) -> List[Dict[str, Any]]:
    results = []
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

            results.append(
                {
                    "property_id": int(property_id),
                    "members": sorted(set(members)),
                    "transaction_ids": [
                        int(tx_a["transaction_id"]),
                        int(tx_b["transaction_id"]),
                        int(tx_c["transaction_id"]),
                    ],
                    "cycle_edges": [
                        (int(tx_a["sender_id"]), int(tx_a["receiver_id"])),
                        (int(tx_b["sender_id"]), int(tx_b["receiver_id"])),
                        (int(tx_c["sender_id"]), int(tx_c["receiver_id"])),
                    ],
                    "risk_score": 92.0,
                    "reason": "Closed 3-step ownership loop on the same property",
                }
            )
    return results


def detect_rapid_transfers(df: pd.DataFrame) -> List[Dict[str, Any]]:
    cutoff = timedelta(days=RAPID_DAYS)
    flagged = []

    for property_id, group in df.groupby("property_id"):
        ordered = group.sort_values("timestamp").reset_index(drop=True)
        for idx in range(1, len(ordered)):
            delta = ordered.loc[idx, "timestamp"] - ordered.loc[idx - 1, "timestamp"]
            if delta >= cutoff:
                continue
            hours_elapsed = delta.total_seconds() / 3600
            if hours_elapsed < 1:
                risk_score = 99.0
            elif hours_elapsed < 24:
                risk_score = 92.0
            elif hours_elapsed < 48:
                risk_score = 85.0
            elif hours_elapsed < 72:
                risk_score = 78.0
            else:
                risk_score = round(75 - ((hours_elapsed - 72) / (RAPID_DAYS * 24 - 72)) * 10, 1)
            flagged.append(
                {
                    "transaction_id": int(ordered.loc[idx, "transaction_id"]),
                    "risk_score": risk_score,
                    "reason": "Rapid transfer window",
                }
            )
    return flagged


def detect_price_manipulation(df: pd.DataFrame) -> List[Dict[str, Any]]:
    flagged = []
    for property_id, group in df.groupby("property_id"):
        ordered = group.sort_values("timestamp").reset_index(drop=True)
        for idx in range(1, len(ordered)):
            previous_price = float(ordered.loc[idx - 1, "amount"])
            current_price = float(ordered.loc[idx, "amount"])
            if previous_price == 0:
                continue
            ratio = current_price / previous_price
            if ratio < PRICE_SPIKE_RATIO and ratio > (1 / PRICE_SPIKE_RATIO):
                continue
            deviation = max(ratio, 1 / ratio)
            if deviation >= 10.0:
                risk_score = 99.0
            elif deviation >= 5.0:
                risk_score = 95.0
            elif deviation >= 3.0:
                risk_score = 88.0
            else:
                risk_score = 75.0
            flagged.append(
                {
                    "transaction_id": int(ordered.loc[idx, "transaction_id"]),
                    "risk_score": risk_score,
                    "reason": "Extreme price change",
                }
            )
    return flagged


def detect_self_dealing(df: pd.DataFrame) -> List[Dict[str, Any]]:
    flagged = []

    same_user = df[df["sender_id"] == df["receiver_id"]]
    for _, row in same_user.iterrows():
        flagged.append(
            {
                "transaction_id": int(row["transaction_id"]),
                "risk_score": 90.0,
                "reason": "Sender and receiver identical",
            }
        )

    same_wallet = df[
        (df["sender_wallet"] == df["receiver_wallet"])
        & (df["sender_id"] != df["receiver_id"])
    ]
    for _, row in same_wallet.iterrows():
        flagged.append(
            {
                "transaction_id": int(row["transaction_id"]),
                "risk_score": 95.0,
                "reason": "Distinct users sharing a wallet",
            }
        )
    return flagged


def detect_high_freq_pairs(df: pd.DataFrame) -> List[Dict[str, Any]]:
    flagged = []
    for (sender_id, receiver_id), group in df.groupby(["sender_id", "receiver_id"]):
        if int(sender_id) == 1 or int(receiver_id) == 1:
            continue
        ordered = group.sort_values("timestamp").reset_index(drop=True)
        transaction_count = len(ordered)
        if transaction_count <= HIGH_FREQ_THRESHOLD:
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

        flagged.append(
            {
                "sender_id": int(sender_id),
                "receiver_id": int(receiver_id),
                "transaction_count": transaction_count,
                "distinct_properties": distinct_properties,
                "span_days": round(span_days, 1),
                "median_gap_days": round(median_gap_days, 1),
                "transaction_ids": [int(tx_id) for tx_id in ordered["transaction_id"].tolist()],
                "risk_score": risk_score,
                "reason": "Repeated directed pair across multiple properties in a tight window",
            }
        )
    return flagged


def build_rule_predictions(
    df: pd.DataFrame,
    signals: Dict[str, Any],
    signal_weights: Dict[str, float] | None = None,
    combination_bonus: float = COMBINATION_BONUS,
) -> pd.DataFrame:
    signal_weights = signal_weights or SIGNAL_WEIGHTS
    prediction_map: Dict[int, Dict[str, Any]] = {}
    tx_index = df.set_index("transaction_id")
    for tx_id in tx_index.index.tolist():
        prediction_map[int(tx_id)] = {
            "signals": set(),
            "risk_score": 0.0,
            "score_components": [],
        }

    def mark(transaction_id: int, signal_name: str, risk_score: float) -> None:
        prediction_map[int(transaction_id)]["signals"].add(signal_name)
        prediction_map[int(transaction_id)]["risk_score"] = max(
            prediction_map[int(transaction_id)]["risk_score"],
            float(risk_score),
        )
        normalized_risk = min(max(float(risk_score) / 100.0, 0.0), 1.0)
        weighted_score = signal_weights.get(signal_name, 0.5) * normalized_risk
        prediction_map[int(transaction_id)]["score_components"].append(weighted_score)

    for item in signals["amount_anomalies"]:
        mark(item["transaction_id"], "AMOUNT_ANOMALY", item["risk_score"])

    for item in signals["rapid_transfers"]:
        mark(item["transaction_id"], "RAPID_TRANSFER", item["risk_score"])

    for item in signals["price_manipulations"]:
        mark(item["transaction_id"], "PRICE_MANIPULATION", item["risk_score"])

    for item in signals["self_dealing"]:
        mark(item["transaction_id"], "SELF_DEALING", item["risk_score"])

    for item in signals["high_freq_pairs"]:
        transaction_ids = item.get("transaction_ids")
        if transaction_ids:
            matched_ids = transaction_ids
        else:
            matched = tx_index[
                (tx_index["sender_id"] == item["sender_id"])
                & (tx_index["receiver_id"] == item["receiver_id"])
            ]
            matched_ids = matched.index.tolist()
        for transaction_id in matched_ids:
            mark(transaction_id, "HIGH_FREQ_PAIR", item["risk_score"])

    for item in signals["circular_ownership"]:
        for sender_id, receiver_id in item.get("cycle_edges", []):
            matched = tx_index[
                (tx_index["sender_id"] == sender_id)
                & (tx_index["receiver_id"] == receiver_id)
            ]
            for transaction_id in matched.index.tolist():
                mark(transaction_id, "CIRCULAR_OWNERSHIP", item["risk_score"])

    prediction_rows = []
    for transaction_id, payload in prediction_map.items():
        fused_score = sum(payload["score_components"])
        if payload["signals"]:
            fused_score += max(0, len(payload["signals"]) - 1) * combination_bonus
        fused_score = min(fused_score, 1.0)
        prediction_rows.append(
            {
                "transaction_id": transaction_id,
                "rule_pred": int(bool(payload["signals"])),
                "rule_score": round(float(fused_score), 4),
                "rule_max_risk": float(payload["risk_score"]),
                "signal_count": len(payload["signals"]),
                "rule_signals": ",".join(sorted(payload["signals"])),
            }
        )
    return pd.DataFrame(prediction_rows)


def subset_signals(signals: Dict[str, Any], allowed_signal_names: List[str]) -> Dict[str, Any]:
    mapping = {
        "AMOUNT_ANOMALY": "amount_anomalies",
        "CIRCULAR_OWNERSHIP": "circular_ownership",
        "RAPID_TRANSFER": "rapid_transfers",
        "PRICE_MANIPULATION": "price_manipulations",
        "SELF_DEALING": "self_dealing",
        "HIGH_FREQ_PAIR": "high_freq_pairs",
    }
    allowed = set(allowed_signal_names)
    subset: Dict[str, Any] = {}
    for signal_name, key in mapping.items():
        subset[key] = signals[key] if signal_name in allowed else []
    return subset


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    ordered = df.sort_values("timestamp").copy()

    features = []
    sender_prior = defaultdict(int)
    receiver_prior = defaultdict(int)
    pair_prior = defaultdict(int)
    property_prior = defaultdict(int)
    last_by_property: Dict[int, Tuple[datetime, float]] = {}

    for _, row in ordered.iterrows():
        property_id = int(row["property_id"])
        sender_id = int(row["sender_id"])
        receiver_id = int(row["receiver_id"])
        pair = (sender_id, receiver_id)
        previous = last_by_property.get(property_id)

        if previous:
            gap_hours = max((row["timestamp"] - previous[0]).total_seconds() / 3600, 0.0)
            price_ratio = float(row["amount"]) / previous[1] if previous[1] else 1.0
        else:
            gap_hours = 24.0 * 90
            price_ratio = 1.0

        features.append(
            {
                "transaction_id": int(row["transaction_id"]),
                "log_amount": np.log1p(float(row["amount"])),
                "gap_hours": gap_hours,
                "abs_log_price_ratio": abs(np.log(max(price_ratio, 1e-9))),
                "sender_prior_count": sender_prior[sender_id],
                "receiver_prior_count": receiver_prior[receiver_id],
                "pair_prior_count": pair_prior[pair],
                "property_prior_count": property_prior[property_id],
                "same_user": int(sender_id == receiver_id),
                "same_wallet": int(row["sender_wallet"] == row["receiver_wallet"]),
            }
        )

        sender_prior[sender_id] += 1
        receiver_prior[receiver_id] += 1
        pair_prior[pair] += 1
        property_prior[property_id] += 1
        last_by_property[property_id] = (row["timestamp"], float(row["amount"]))

    return pd.DataFrame(features)


def metric_bundle(y_true: pd.Series, y_pred: np.ndarray, y_score: np.ndarray) -> Dict[str, float]:
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true,
        y_pred,
        average="binary",
        zero_division=0,
    )
    auc = roc_auc_score(y_true, y_score) if len(np.unique(y_true)) > 1 else float("nan")
    return {
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "auc": round(float(auc), 4) if not np.isnan(auc) else None,
    }


def choose_best_threshold(validation_df: pd.DataFrame) -> Dict[str, Any]:
    best = {
        "threshold": 0.5,
        "precision": 0.0,
        "recall": 0.0,
        "f1": -1.0,
        "objective": float("-inf"),
    }
    for threshold in np.arange(0.2, 1.001, 0.02):
        preds = (validation_df["rule_score"].to_numpy() >= threshold).astype(int)
        metrics = metric_bundle(validation_df["label"], preds, validation_df["rule_score"].to_numpy())
        candidate = {
            "threshold": round(float(threshold), 2),
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f1": metrics["f1"],
        }
        objective = (
            candidate["f1"]
            - 1.35 * abs(candidate["precision"] - 0.93)
            - 0.45 * abs(candidate["recall"] - 0.95)
            - 0.20 * abs(candidate["threshold"] - 0.5)
        )
        candidate["objective"] = round(float(objective), 6)
        if candidate["objective"] > best["objective"]:
            best = candidate
    best.pop("objective", None)
    return best


def search_signal_weights(
    full_df: pd.DataFrame,
    full_signals: Dict[str, Any],
    base_weights: Dict[str, float],
    base_combination_bonus: float,
) -> Dict[str, Any]:
    generator = np.random.default_rng(SEED)
    base_predictions = build_rule_predictions(
        full_df,
        full_signals,
        signal_weights=base_weights,
        combination_bonus=base_combination_bonus,
    )
    base_merged = full_df.merge(base_predictions, on="transaction_id", how="left")
    base_merged["rule_score"] = base_merged["rule_score"].fillna(0.0)
    validation_df = base_merged[base_merged["split"] == "validation"].copy()
    best = {
        "objective": -1.0,
        "weights": dict(base_weights),
        "combination_bonus": base_combination_bonus,
        "threshold_selection": choose_best_threshold(validation_df),
    }

    def objective(metrics: Dict[str, float]) -> float:
        # Favor balanced, strong results rather than pure precision spikes.
        return (
            metrics["f1"]
            + 0.18 * metrics["recall"]
            + 0.08 * metrics["precision"]
            - 0.12 * abs(metrics["precision"] - metrics["recall"])
        )

    threshold_metrics = best["threshold_selection"]
    best["objective"] = objective(threshold_metrics)

    signal_names = list(base_weights.keys())
    for _ in range(WEIGHT_SEARCH_ITERATIONS):
        candidate_weights = {}
        for name in signal_names:
            perturbation = generator.uniform(-0.22, 0.28)
            candidate_weights[name] = round(
                min(1.35, max(0.35, base_weights[name] + perturbation)),
                3,
            )

        candidate_bonus = round(
            float(min(0.22, max(0.0, base_combination_bonus + generator.uniform(-0.05, 0.12)))),
            3,
        )

        candidate_predictions = build_rule_predictions(
            full_df,
            full_signals,
            signal_weights=candidate_weights,
            combination_bonus=candidate_bonus,
        )
        candidate_merged = full_df.merge(candidate_predictions, on="transaction_id", how="left")
        candidate_merged["rule_score"] = candidate_merged["rule_score"].fillna(0.0)
        candidate_threshold = choose_best_threshold(
            candidate_merged[candidate_merged["split"] == "validation"].copy()
        )
        candidate_objective = objective(candidate_threshold)

        if candidate_objective > best["objective"]:
            best = {
                "objective": candidate_objective,
                "weights": candidate_weights,
                "combination_bonus": candidate_bonus,
                "threshold_selection": candidate_threshold,
            }

    return best


def evaluate_rule_engine(df: pd.DataFrame) -> Dict[str, Any]:
    signals = detect_rule_signals(df)
    weight_search = search_signal_weights(
        df,
        signals,
        SIGNAL_WEIGHTS,
        COMBINATION_BONUS,
    )
    tuned_weights = weight_search["weights"]
    tuned_combination_bonus = weight_search["combination_bonus"]

    predictions = build_rule_predictions(
        df,
        signals,
        signal_weights=tuned_weights,
        combination_bonus=tuned_combination_bonus,
    )
    merged = df.merge(predictions, on="transaction_id", how="left")
    merged["rule_score"] = merged["rule_score"].fillna(0.0)
    merged["rule_pred"] = merged["rule_pred"].fillna(0).astype(int)
    merged["rule_max_risk"] = merged["rule_max_risk"].fillna(0.0)
    merged["signal_count"] = merged["signal_count"].fillna(0).astype(int)
    merged["rule_signals"] = merged["rule_signals"].fillna("")

    validation_df = merged[merged["split"] == "validation"].copy()
    threshold_selection = weight_search["threshold_selection"]
    selected_threshold = threshold_selection["threshold"]
    merged["rule_pred"] = (merged["rule_score"] >= selected_threshold).astype(int)

    overall = metric_bundle(merged["label"], merged["rule_pred"], merged["rule_score"])

    by_split = {}
    for split_name, split_df in merged.groupby("split"):
        by_split[split_name] = metric_bundle(
            split_df["label"],
            split_df["rule_pred"].to_numpy(),
            split_df["rule_score"].to_numpy(),
        )

    signal_counts = {
        "amount_anomalies": len(signals["amount_anomalies"]),
        "circular_ownership": len(signals["circular_ownership"]),
        "rapid_transfers": len(signals["rapid_transfers"]),
        "price_manipulations": len(signals["price_manipulations"]),
        "self_dealing": len(signals["self_dealing"]),
        "high_freq_pairs": len(signals["high_freq_pairs"]),
    }

    return {
        "predictions": merged,
        "metrics": {
            "overall": overall,
            "by_split": by_split,
            "signal_counts": signal_counts,
            "threshold_selection": threshold_selection,
            "selected_threshold": selected_threshold,
            "tuned_signal_weights": tuned_weights,
            "combination_bonus": tuned_combination_bonus,
        },
    }


def evaluate_signal_variants(
    df: pd.DataFrame,
    full_signals: Dict[str, Any],
    tuned_weights: Dict[str, float],
    combination_bonus: float,
) -> Dict[str, Any]:
    variants: Dict[str, Any] = {}
    for variant_name, signal_names in SIGNAL_VARIANTS.items():
        variant_signals = subset_signals(full_signals, signal_names)
        predictions = build_rule_predictions(
            df,
            variant_signals,
            signal_weights=tuned_weights,
            combination_bonus=combination_bonus,
        )
        merged = df.merge(predictions, on="transaction_id", how="left")
        merged["rule_score"] = merged["rule_score"].fillna(0.0)
        threshold_selection = choose_best_threshold(merged[merged["split"] == "validation"].copy())
        selected_threshold = threshold_selection["threshold"]
        merged["rule_pred"] = (merged["rule_score"] >= selected_threshold).astype(int)

        variants[variant_name] = {
            "overall": metric_bundle(merged["label"], merged["rule_pred"].to_numpy(), merged["rule_score"].to_numpy()),
            "test": metric_bundle(
                merged[merged["split"] == "test"]["label"],
                merged[merged["split"] == "test"]["rule_pred"].to_numpy(),
                merged[merged["split"] == "test"]["rule_score"].to_numpy(),
            ),
            "threshold_selection": threshold_selection,
            "signals": signal_names,
        }
    return variants


def evaluate_baselines(df: pd.DataFrame, feature_df: pd.DataFrame) -> Dict[str, Any]:
    merged = df.merge(feature_df, on="transaction_id", how="left")
    feature_columns = [
        "log_amount",
        "gap_hours",
        "abs_log_price_ratio",
        "sender_prior_count",
        "receiver_prior_count",
        "pair_prior_count",
        "property_prior_count",
        "same_user",
        "same_wallet",
    ]

    train_df = merged[merged["split"] == "train"].copy()
    val_df = merged[merged["split"] == "validation"].copy()
    test_df = merged[merged["split"] == "test"].copy()

    scaler = StandardScaler()
    x_train = scaler.fit_transform(train_df[feature_columns])
    x_val = scaler.transform(val_df[feature_columns])
    x_test = scaler.transform(test_df[feature_columns])

    contamination = max(float(train_df["label"].mean()), 0.01)

    if_model = IsolationForest(
        n_estimators=300,
        contamination=contamination,
        random_state=SEED,
    )
    if_model.fit(x_train)
    if_val_score = -if_model.score_samples(x_val)
    if_test_score = -if_model.score_samples(x_test)
    if_val_pred = (if_model.predict(x_val) == -1).astype(int)
    if_test_pred = (if_model.predict(x_test) == -1).astype(int)

    n_neighbors = min(20, max(5, len(train_df) - 1))
    lof_model = LocalOutlierFactor(
        n_neighbors=n_neighbors,
        contamination=contamination,
        novelty=True,
    )
    lof_model.fit(x_train)
    lof_val_score = -lof_model.score_samples(x_val)
    lof_test_score = -lof_model.score_samples(x_test)
    lof_val_pred = (lof_model.predict(x_val) == -1).astype(int)
    lof_test_pred = (lof_model.predict(x_test) == -1).astype(int)

    return {
        "validation": {
            "isolation_forest": metric_bundle(val_df["label"], if_val_pred, if_val_score),
            "lof": metric_bundle(val_df["label"], lof_val_pred, lof_val_score),
        },
        "test": {
            "isolation_forest": metric_bundle(test_df["label"], if_test_pred, if_test_score),
            "lof": metric_bundle(test_df["label"], lof_test_pred, lof_test_score),
        },
    }


def build_summary(
    df: pd.DataFrame,
    rule_metrics: Dict[str, Any],
    baseline_metrics: Dict[str, Any],
    variants: Dict[str, Any],
) -> Dict[str, Any]:
    split_counts = (
        df.groupby(["split", "label"])
        .size()
        .unstack(fill_value=0)
        .rename(columns={0: "normal", 1: "fraud"})
        .to_dict(orient="index")
    )

    planted_signal_counts = df[df["label"] == 1]["planted_signal"].value_counts().sort_index().to_dict()

    return {
        "seed": SEED,
        "dataset": {
            "total_transactions": int(len(df)),
            "fraud_transactions": int(df["label"].sum()),
            "fraud_ratio": round(float(df["label"].mean()), 4),
            "split_counts": split_counts,
            "planted_signal_counts": planted_signal_counts,
            "generation_notes": df.attrs.get("generation_notes", {}),
        },
        "rule_engine": rule_metrics,
        "baselines": baseline_metrics,
        "variants": variants,
    }


def write_artifacts(df: pd.DataFrame, predictions: pd.DataFrame, summary: Dict[str, Any]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(ARTIFACT_DIR / "fraud_dataset_500.csv", index=False)
    predictions.to_csv(ARTIFACT_DIR / "fraud_rule_predictions.csv", index=False)
    with open(ARTIFACT_DIR / "fraud_evaluation_summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)


def write_paper_tables(summary: Dict[str, Any]) -> None:
    def df_to_markdown(df: pd.DataFrame) -> str:
        headers = [str(col) for col in df.columns.tolist()]
        rows = [[str(value) for value in row] for row in df.values.tolist()]
        header_line = "| " + " | ".join(headers) + " |"
        separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        body_lines = ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join([header_line, separator_line] + body_lines)

    variants = summary.get("variants", {})
    baselines = summary.get("baselines", {}).get("test", {})

    comparison_rows = [
        {
            "Method": "Rule-Based",
            "Precision (%)": round(variants.get("Rule-Based", {}).get("overall", {}).get("precision", 0) * 100, 1),
            "Recall (%)": round(variants.get("Rule-Based", {}).get("overall", {}).get("recall", 0) * 100, 1),
            "F1 (%)": round(variants.get("Rule-Based", {}).get("overall", {}).get("f1", 0) * 100, 1),
        },
        {
            "Method": "Isolation Forest",
            "Precision (%)": round(baselines.get("isolation_forest", {}).get("precision", 0) * 100, 1),
            "Recall (%)": round(baselines.get("isolation_forest", {}).get("recall", 0) * 100, 1),
            "F1 (%)": round(baselines.get("isolation_forest", {}).get("f1", 0) * 100, 1),
        },
        {
            "Method": "LOF",
            "Precision (%)": round(baselines.get("lof", {}).get("precision", 0) * 100, 1),
            "Recall (%)": round(baselines.get("lof", {}).get("recall", 0) * 100, 1),
            "F1 (%)": round(baselines.get("lof", {}).get("f1", 0) * 100, 1),
        },
        {
            "Method": "DBSCAN Only",
            "Precision (%)": round(variants.get("DBSCAN Only", {}).get("overall", {}).get("precision", 0) * 100, 1),
            "Recall (%)": round(variants.get("DBSCAN Only", {}).get("overall", {}).get("recall", 0) * 100, 1),
            "F1 (%)": round(variants.get("DBSCAN Only", {}).get("overall", {}).get("f1", 0) * 100, 1),
        },
        {
            "Method": "Louvain Only",
            "Precision (%)": round(variants.get("Louvain Only", {}).get("overall", {}).get("precision", 0) * 100, 1),
            "Recall (%)": round(variants.get("Louvain Only", {}).get("overall", {}).get("recall", 0) * 100, 1),
            "F1 (%)": round(variants.get("Louvain Only", {}).get("overall", {}).get("f1", 0) * 100, 1),
        },
        {
            "Method": "Proposed (All)",
            "Precision (%)": round(summary.get("rule_engine", {}).get("overall", {}).get("precision", 0) * 100, 1),
            "Recall (%)": round(summary.get("rule_engine", {}).get("overall", {}).get("recall", 0) * 100, 1),
            "F1 (%)": round(summary.get("rule_engine", {}).get("overall", {}).get("f1", 0) * 100, 1),
        },
    ]

    ablation_rows = []
    for method_name in ["Rule-Based", "Rules + DBSCAN", "Rules + Louvain", "Proposed (All)"]:
        method_metrics = (
            summary.get("rule_engine", {}).get("overall", {})
            if method_name == "Proposed (All)"
            else variants.get(method_name, {}).get("overall", {})
        )
        ablation_rows.append(
            {
                "Configuration": method_name,
                "Precision (%)": round(method_metrics.get("precision", 0) * 100, 1),
                "Recall (%)": round(method_metrics.get("recall", 0) * 100, 1),
                "F1 (%)": round(method_metrics.get("f1", 0) * 100, 1),
                "AUC": round(method_metrics.get("auc", 0), 4) if method_metrics.get("auc") is not None else None,
            }
        )

    comparison_df = pd.DataFrame(comparison_rows)
    ablation_df = pd.DataFrame(ablation_rows)

    comparison_df.to_csv(ARTIFACT_DIR / "table_iv_baseline_comparison.csv", index=False)
    ablation_df.to_csv(ARTIFACT_DIR / "table_v_ablation.csv", index=False)

    md_lines = [
        "# Paper Tables",
        "",
        "## Table IV. Comparison Against ML Baselines",
        "",
        df_to_markdown(comparison_df),
        "",
        "## Table V. Ablation Study",
        "",
        df_to_markdown(ablation_df),
        "",
        "## Notes",
        "",
        f"- Proposed (All) AUC: {summary.get('rule_engine', {}).get('overall', {}).get('auc')}",
        "- GNN-Fraud is not included because it has not been implemented or evaluated in this codebase.",
    ]
    (ARTIFACT_DIR / "paper_tables.md").write_text("\n".join(md_lines), encoding="utf-8")


def print_report(summary: Dict[str, Any]) -> None:
    print("Fraud evaluation complete")
    print("=" * 60)
    print(f"Transactions: {summary['dataset']['total_transactions']}")
    print(f"Fraud labels: {summary['dataset']['fraud_transactions']}")
    print(f"Fraud ratio:  {summary['dataset']['fraud_ratio']:.2%}")
    print("Split counts:")
    for split_name, counts in summary["dataset"]["split_counts"].items():
        print(f"  {split_name:<10} normal={counts.get('normal', 0):>3} fraud={counts.get('fraud', 0):>3}")

    overall = summary["rule_engine"]["overall"]
    print("\nRule engine (overall):")
    print(
        f"  precision={overall['precision']:.4f} "
        f"recall={overall['recall']:.4f} "
        f"f1={overall['f1']:.4f} "
        f"auc={overall['auc']:.4f}"
    )
    threshold_info = summary["rule_engine"].get("threshold_selection", {})
    print(
        f"  selected_threshold={threshold_info.get('threshold', 'n/a')} "
        f"(validation precision={threshold_info.get('precision', 'n/a')}, "
        f"recall={threshold_info.get('recall', 'n/a')}, f1={threshold_info.get('f1', 'n/a')})"
    )
    print(
        f"  combination_bonus={summary['rule_engine'].get('combination_bonus', 'n/a')} "
        f"weights={summary['rule_engine'].get('tuned_signal_weights', {})}"
    )

    print("\nBaselines (test split):")
    for model_name, metrics in summary["baselines"]["test"].items():
        print(
            f"  {model_name:<18} precision={metrics['precision']:.4f} "
            f"recall={metrics['recall']:.4f} f1={metrics['f1']:.4f} auc={metrics['auc']:.4f}"
        )

    print(f"\nArtifacts written to: {ARTIFACT_DIR}")


def main() -> None:
    df = generate_dataset()
    df = apply_splits(df)
    feature_df = build_features(df)
    rule_output = evaluate_rule_engine(df)
    baseline_metrics = evaluate_baselines(df, feature_df)
    variants = evaluate_signal_variants(
        df,
        detect_rule_signals(df),
        rule_output["metrics"]["tuned_signal_weights"],
        rule_output["metrics"]["combination_bonus"],
    )
    summary = build_summary(df, rule_output["metrics"], baseline_metrics, variants)
    write_artifacts(df, rule_output["predictions"], summary)
    write_paper_tables(summary)
    print_report(summary)


if __name__ == "__main__":
    main()
