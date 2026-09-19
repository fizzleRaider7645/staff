"""Insights: deterministic, explainable observations over the ledger.

Every insight names its evidence (transaction ids, a series id) and a
suggested action, so Claude and the dashboard can show why it fired rather
than just that it did. Keys are stable so a dismissal sticks.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field

from ledger import db, recurring, reports
from ledger.money import epoch_to_date, month_of

SEVERITY_RANK = {"info": 0, "notice": 1, "warn": 2, "alert": 3}


@dataclass
class Insight:
    kind: str
    severity: str
    title: str
    detail: str
    key: str
    amount_cents: int = 0
    evidence: list[str] = field(default_factory=list)
    series_id: str | None = None
    suggested_action: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    conn: sqlite3.Connection
    now: int
    today: str
    month: str
    roster: list[dict]          # active series, user overrides applied, ignored removed
    net_worth: dict


def context(conn: sqlite3.Connection, now: int | None = None, redetect: bool = True) -> Context:
    now = now or db.now_epoch()
    if redetect:
        recurring.redetect(conn, now)
    today = epoch_to_date(now)
    return Context(conn=conn, now=now, today=today, month=month_of(today),
                   roster=recurring.roster(conn), net_worth=reports.net_worth(conn))


def modules():
    from ledger.insights import (budgets, duplicates, fees, goals, mom, obligations, overlap,
                                 price, subscriptions, unusual)
    return [subscriptions, price, overlap, fees, unusual, obligations, goals, budgets, mom, duplicates]


def run_all(conn: sqlite3.Connection, now: int | None = None, *, kinds=None, min_severity: str = "info",
            include_dismissed: bool = False, ctx: Context | None = None) -> list[Insight]:
    ctx = ctx or context(conn, now)
    dismissed = set() if include_dismissed else {r["key"] for r in db.rows(conn, "SELECT key FROM insight_dismissals")}
    floor = SEVERITY_RANK.get(min_severity, 0)
    out: list[Insight] = []
    for mod in modules():
        for ins in mod.compute(ctx):
            if kinds and ins.kind not in kinds:
                continue
            if ins.key in dismissed or SEVERITY_RANK[ins.severity] < floor:
                continue
            out.append(ins)
    out.sort(key=lambda i: (-SEVERITY_RANK[i.severity], -abs(i.amount_cents), i.kind))
    return out


def dismiss(conn: sqlite3.Connection, key: str, by: str = "user", now: int | None = None) -> None:
    conn.execute("INSERT INTO insight_dismissals (key, dismissed_at, by) VALUES (?, ?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET dismissed_at = excluded.dismissed_at, by = excluded.by",
                 (key, now or db.now_epoch(), by))
    conn.commit()


def undismiss(conn: sqlite3.Connection, key: str) -> bool:
    cur = conn.execute("DELETE FROM insight_dismissals WHERE key = ?", (key,))
    conn.commit()
    return cur.rowcount > 0
