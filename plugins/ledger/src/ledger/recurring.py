"""Find charges that repeat.

A series is one payee on one account whose charges land at a steady cadence.
Cadence comes from the median gap between charges; the fit is the share of
gaps inside that cadence's tolerance. Amount stability (coefficient of
variation) separates a subscription (Netflix, same price every month) from a
bill (PG&E, monthly but variable). Series ids are deterministic so the
user's overrides survive every re-detection.
"""
from __future__ import annotations

import hashlib
import sqlite3
import statistics
from dataclasses import asdict, dataclass, field

from ledger import catalog, db

DAY = 86400
CADENCES = [  # name, interval days, tolerance days
    ("weekly", 7, 2),
    ("biweekly", 14, 3),
    ("monthly", 30, 5),
    ("quarterly", 91, 10),
    ("annual", 365, 25),
]
MONTHLY_FACTOR = {"weekly": 52 / 12, "biweekly": 26 / 12, "monthly": 1.0, "quarterly": 1 / 3, "annual": 1 / 12}
MIN_FIT = 0.7
SUBSCRIPTION_CV = 0.25
# Recurring but not a subscription in the everyday sense; they show up as bills.
BILL_CATEGORIES = {"Housing", "Utilities", "Insurance", "Taxes", "Investments", "Education",
                   "Transfer", "Income", "Fees & Interest", "Cash & ATM"}


@dataclass
class Series:
    id: str
    payee_key: str
    account_id: str
    cadence: str
    interval_days: int
    typical_amount_cents: int
    last_amount_cents: int
    first_seen: int
    last_seen: int
    next_expected: int
    occurrences: int
    confidence: float
    status: str
    is_subscription: bool
    kind: str                     # subscription|bill|variable
    service_id: str | None
    category: str | None
    members: list[str] = field(default_factory=list)
    amounts: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def series_id(account_id: str, payee_key: str, cadence: str) -> str:
    return hashlib.sha1(f"{account_id}|{payee_key}|{cadence}".encode()).hexdigest()[:16]


def classify(gaps: list[int]) -> tuple[str, int, float] | None:
    """(cadence, interval_days, fit) for a list of day gaps, or None."""
    if not gaps:
        return None
    median = statistics.median(gaps)
    best = None
    for name, interval, tol in CADENCES:
        if abs(median - interval) <= tol:
            fit = sum(1 for g in gaps if abs(g - interval) <= tol) / len(gaps)
            if fit >= MIN_FIT and (best is None or fit > best[2]):
                best = (name, interval, fit)
    return best


def monthly_equivalent(amount_cents: int, cadence: str) -> int:
    return int(round(abs(amount_cents) * MONTHLY_FACTOR.get(cadence, 1.0)))


def _cv(amounts: list[int]) -> float:
    if len(amounts) < 2:
        return 0.0
    mean = statistics.mean(amounts)
    if mean == 0:
        return 1.0
    return statistics.pstdev(amounts) / abs(mean)


def detect(conn: sqlite3.Connection, now: int) -> list[Series]:
    rows = db.rows(conn, """
        SELECT t.id, t.account_id, t.payee_key, t.posted, t.amount_cents, t.description,
               c.name AS category, c.kind AS category_kind
        FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.removed_at IS NULL AND t.ignored = 0 AND t.pending = 0
          AND t.account_id NOT IN (SELECT id FROM accounts WHERE hidden = 1)
          AND t.amount_cents <= 0 AND t.payee_key != ''
          AND COALESCE(c.kind, 'expense') NOT IN ('transfer', 'income')
        ORDER BY t.account_id, t.payee_key, t.posted""")
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["account_id"], r["payee_key"]), []).append(r)

    out: list[Series] = []
    for (account_id, key), items in groups.items():
        if len(items) < 2:
            continue
        gaps = [round((b["posted"] - a["posted"]) / DAY) for a, b in zip(items, items[1:])]
        if len(items) == 2:
            # Two data points only support an annual claim (a yearly renewal).
            cls = classify(gaps)
            if not cls or cls[0] != "annual":
                continue
        else:
            cls = classify(gaps)
            if not cls:
                continue
        cadence, interval, fit = cls
        # $0 rows are trial periods and authorisations: they belong to the
        # series (the trial insight needs them) but say nothing about price.
        amounts = [abs(i["amount_cents"]) for i in items]
        charged = [a for a in amounts if a > 0]
        if not charged:
            continue
        cv = _cv(charged)
        confidence = round(0.6 * fit + 0.4 * (1 - min(cv, 1.0)), 3)
        last = items[-1]
        category = next((i["category"] for i in reversed(items) if i["category"]), None)
        svc = catalog.match_service(last["description"])
        stable = cv <= SUBSCRIPTION_CV
        if category in BILL_CATEGORIES:
            kind = "bill" if stable else "variable"
        else:
            kind = "subscription" if stable else "variable"
        lapse_factor = 1.2 if cadence == "annual" else 1.5
        status = "active" if last["posted"] >= now - lapse_factor * interval * DAY else "lapsed"
        out.append(Series(
            id=series_id(account_id, key, cadence), payee_key=key, account_id=account_id,
            cadence=cadence, interval_days=interval,
            typical_amount_cents=int(statistics.median(charged)), last_amount_cents=amounts[-1],
            first_seen=items[0]["posted"], last_seen=last["posted"],
            next_expected=last["posted"] + interval * DAY, occurrences=len(items),
            confidence=confidence, status=status, is_subscription=(kind == "subscription"), kind=kind,
            service_id=svc["id"] if svc else None, category=category,
            members=[i["id"] for i in items], amounts=amounts,
        ))
    return out


def save(conn: sqlite3.Connection, found: list[Series], now: int) -> None:
    """Rewrite detected columns; keep user_* overrides; drop series that no
    longer exist unless the user touched them."""
    keep = {s.id for s in found}
    for s in found:
        conn.execute(
            """INSERT INTO series (id, payee_key, account_id, cadence, interval_days, typical_amount_cents,
                 last_amount_cents, first_seen, last_seen, next_expected, occurrences, confidence, status,
                 is_subscription, service_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET payee_key = excluded.payee_key, cadence = excluded.cadence,
                 interval_days = excluded.interval_days, typical_amount_cents = excluded.typical_amount_cents,
                 last_amount_cents = excluded.last_amount_cents, first_seen = excluded.first_seen,
                 last_seen = excluded.last_seen, next_expected = excluded.next_expected,
                 occurrences = excluded.occurrences, confidence = excluded.confidence, status = excluded.status,
                 is_subscription = excluded.is_subscription, service_id = excluded.service_id,
                 updated_at = excluded.updated_at""",
            (s.id, s.payee_key, s.account_id, s.cadence, s.interval_days, s.typical_amount_cents,
             s.last_amount_cents, s.first_seen, s.last_seen, s.next_expected, s.occurrences, s.confidence,
             s.status, 1 if s.is_subscription else 0, s.service_id, now),
        )
        conn.execute("DELETE FROM series_members WHERE series_id = ?", (s.id,))
        conn.executemany("INSERT OR IGNORE INTO series_members (series_id, transaction_id) VALUES (?, ?)",
                         [(s.id, m) for m in s.members])
    stale = db.rows(conn, "SELECT id, user_label, user_status, user_is_subscription FROM series")
    for r in stale:
        if r["id"] in keep:
            continue
        if r["user_label"] or r["user_status"] or r["user_is_subscription"] is not None:
            conn.execute("UPDATE series SET status = 'lapsed', updated_at = ? WHERE id = ?", (now, r["id"]))
        else:
            conn.execute("DELETE FROM series WHERE id = ?", (r["id"],))
            conn.execute("DELETE FROM series_members WHERE series_id = ?", (r["id"],))
    conn.commit()


def redetect(conn: sqlite3.Connection, now: int) -> list[Series]:
    found = detect(conn, now)
    save(conn, found, now)
    return found


def roster(conn: sqlite3.Connection, *, include_lapsed: bool = False, include_ignored: bool = False,
           subscriptions_only: bool = False) -> list[dict]:
    """Series with the user's overrides applied and a monthly-equivalent cost."""
    rows = db.rows(conn, """
        SELECT s.*, a.name AS account, a.currency,
               (SELECT c.name FROM series_members m JOIN transactions t ON t.id = m.transaction_id
                  LEFT JOIN categories c ON c.id = t.category_id
                  WHERE m.series_id = s.id AND c.name IS NOT NULL ORDER BY t.posted DESC LIMIT 1) AS category
        FROM series s LEFT JOIN accounts a ON a.id = s.account_id
        ORDER BY s.status, s.typical_amount_cents DESC""")
    out = []
    for r in rows:
        status = r["user_status"] or r["status"]
        if status == "ignored" and not include_ignored:
            continue
        if status == "lapsed" and not include_lapsed:
            continue
        is_sub = bool(r["user_is_subscription"]) if r["user_is_subscription"] is not None else bool(r["is_subscription"])
        if subscriptions_only and not is_sub:
            continue
        svc = catalog.service(r["service_id"]) if r["service_id"] else None
        label = r["user_label"] or (svc["name"] if svc else r["payee_key"].title())
        out.append({
            "id": r["id"], "label": label, "payee_key": r["payee_key"], "account": r["account"],
            "account_id": r["account_id"], "cadence": r["cadence"], "interval_days": r["interval_days"],
            "typical_amount_cents": r["typical_amount_cents"], "last_amount_cents": r["last_amount_cents"],
            "monthly_cents": monthly_equivalent(r["typical_amount_cents"], r["cadence"]),
            "first_seen": r["first_seen"], "last_seen": r["last_seen"], "next_expected": r["next_expected"],
            "occurrences": r["occurrences"], "confidence": r["confidence"], "status": status,
            "is_subscription": is_sub, "service": catalog.public(svc) if svc else None,
            "category": r["category"], "user_label": r["user_label"],
        })
    return out


def set_override(conn: sqlite3.Connection, series_id_: str, *, label: str | None = None,
                 status: str | None = None, is_subscription: bool | None = None, now: int | None = None) -> bool:
    sets, params = [], []
    if label is not None:
        sets.append("user_label = ?"); params.append(label or None)
    if status is not None:
        sets.append("user_status = ?"); params.append(status or None)
    if is_subscription is not None:
        sets.append("user_is_subscription = ?"); params.append(1 if is_subscription else 0)
    if not sets:
        return False
    sets.append("updated_at = ?"); params.append(now or db.now_epoch())
    params.append(series_id_)
    cur = conn.execute(f"UPDATE series SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    return cur.rowcount > 0


def amounts_for(conn: sqlite3.Connection, series_id_: str) -> list[tuple[int, int]]:
    """[(posted, abs amount)] oldest first."""
    return [(r["posted"], abs(r["amount_cents"])) for r in db.rows(conn, """
        SELECT t.posted, t.amount_cents FROM series_members m JOIN transactions t ON t.id = m.transaction_id
        WHERE m.series_id = ? AND t.removed_at IS NULL ORDER BY t.posted""", (series_id_,))]
