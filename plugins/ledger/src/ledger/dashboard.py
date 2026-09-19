"""The dashboard: one self-contained HTML file rendered from the database.

Everything is computed here in Python and written as markup plus inline SVG,
so the file works from disk, with scripts disabled, and as a private
artifact. The numbers are also embedded as JSON for anything that wants to
read them later.
"""
from __future__ import annotations

import html
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from ledger import budgets, config, db, goals, insights, recurring, reports, svg, sync
from ledger.money import add_days, epoch_to_date, fmt, month_bounds, month_of, shift_month

_TEMPLATE = Path(__file__).parent / "data" / "dashboard_template.html"
DAY = 86400


def build_snapshot(conn: sqlite3.Connection, now: int | None = None) -> dict:
    now = now or db.now_epoch()
    today = epoch_to_date(now)
    month = month_of(today)
    ctx = insights.context(conn, now)                 # re-detects series
    found = insights.run_all(conn, now, ctx=ctx)
    nw = ctx.net_worth
    s, e = month_bounds(month)
    ps, pe = month_bounds(shift_month(month, -1))
    this_cats = {r["key"]: r["spent_cents"] for r in reports.spending_summary(conn, s, e)}
    last_cats = {r["key"]: r["spent_cents"] for r in reports.spending_summary(conn, ps, pe)}
    cats = sorted(set(this_cats) | set(last_cats), key=lambda k: -(this_cats.get(k, 0) + last_cats.get(k, 0)))
    subs = [r for r in ctx.roster if r["is_subscription"]]
    bills = [r for r in ctx.roster if not r["is_subscription"]]
    horizon = now + 30 * DAY
    due = sorted((r for r in ctx.roster if r["next_expected"] and now - 3 * DAY <= r["next_expected"] <= horizon),
                 key=lambda r: r["next_expected"])
    accounts = []
    for a in nw["accounts"]:
        hist = reports.balance_history(conn, a["id"], 90, today)
        accounts.append({**a, "history": [h["balance_cents"] for h in hist],
                         "as_of": epoch_to_date(a["balance_date"]) if a["balance_date"] else None})
    last = sync.last_sync(conn)
    return {
        "as_of": today, "month": month, "previous_month": shift_month(month, -1),
        "net_worth_cents": nw["total_cents"], "assets_cents": nw["assets_cents"],
        "liabilities_cents": nw["liabilities_cents"], "cash_cents": nw["cash_cents"],
        "accounts": accounts,
        "this_month": reports.totals(conn, s, e), "last_month": reports.totals(conn, ps, pe),
        "cash_flow": reports.cash_flow(conn, 6, month),
        "categories": [{"name": c, "this_cents": this_cats.get(c, 0), "last_cents": last_cats.get(c, 0)} for c in cats[:12]],
        "subscriptions": subs, "bills": bills,
        "subscriptions_monthly_cents": sum(r["monthly_cents"] for r in subs if r["status"] == "active"),
        "insights": [i.as_dict() for i in found],
        "goals": goals.progress(conn, now),
        "budgets": budgets.summary(conn, month, now),
        "upcoming": due, "upcoming_total_cents": sum(r["typical_amount_cents"] for r in due),
        "last_sync": None if last is None else {
            "at": epoch_to_date(last["started_at"]), "ok": bool(last["ok"]), "kind": last["kind"],
            "errlist": json.loads(last["errlist_json"] or "[]"), "error": last["error"]},
        "history_complete": sync.backfill_done(conn),
        "uncategorized": conn.execute("SELECT COUNT(*) FROM transactions WHERE removed_at IS NULL AND category_id IS NULL").fetchone()[0],
    }


# --- rendering -----------------------------------------------------------

def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _signed(cents: int) -> str:
    cls = "good" if cents >= 0 else "bad"
    return f'<span class="{cls}">{_e(fmt(cents))}</span>'


def _kpi(label: str, value: str) -> str:
    return f'<div class="kpi"><div class="n">{value}</div><div class="l">{_e(label)}</div></div>'


def _accounts(snap) -> str:
    rows = []
    for a in snap["accounts"]:
        rows.append(f"<tr><td>{_e(a['name'])}<div class='muted'>{_e(a['institution'] or '')} · {_e(a['kind'])}</div></td>"
                    f"<td>{svg.sparkline(a['history'])}</td>"
                    f"<td class='num'>{_e(fmt(a['balance_cents'], a['currency']))}</td>"
                    f"<td class='muted'>{_e(a['as_of'] or '')}</td></tr>")
    return ("<table><tr><th>Account</th><th>90 days</th><th class='num'>Balance</th><th>As of</th></tr>"
            + "".join(rows) + "</table>") if rows else '<p class="muted">no accounts yet — run ledger sync</p>'


def _month_card(snap) -> str:
    t, l = snap["this_month"], snap["last_month"]
    return ('<div class="kpis">' + _kpi(f"income {snap['month']}", _e(fmt(t["income_cents"])))
            + _kpi("spending", _e(fmt(t["expense_cents"]))) + _kpi("net", _signed(t["net_cents"]))
            + _kpi(f"spending {snap['previous_month']}", _e(fmt(l["expense_cents"]))) + "</div>"
            + (f"<p class='muted'>{snap['uncategorized']} uncategorized transaction(s)</p>" if snap["uncategorized"] else ""))


def _categories(snap) -> str:
    rows = [(c["name"], c["this_cents"], c["last_cents"]) for c in snap["categories"] if c["this_cents"] or c["last_cents"]]
    return svg.hbars(rows, fmt=fmt) + "<p class='muted'>bar: this month · tick: last month</p>"


def _series_table(rows, empty: str) -> str:
    if not rows:
        return f'<p class="muted">{_e(empty)}</p>'
    out = ["<table><tr><th>Name</th><th>Cadence</th><th class='num'>Amount</th><th class='num'>Per month</th><th>Next</th><th>Status</th></tr>"]
    for r in rows:
        nxt = epoch_to_date(r["next_expected"]) if r["next_expected"] else ""
        out.append(f"<tr><td>{_e(r['label'])}<div class='muted'>{_e(r['account'] or '')}</div></td><td>{_e(r['cadence'])}</td>"
                   f"<td class='num'>{_e(fmt(r['typical_amount_cents']))}</td><td class='num'>{_e(fmt(r['monthly_cents']))}</td>"
                   f"<td>{_e(nxt)}</td><td class='muted'>{_e(r['status'])}</td></tr>")
    return "".join(out) + "</table>"


def _insights(snap) -> str:
    if not snap["insights"]:
        return '<p class="muted">nothing to report</p>'
    out = []
    for i in snap["insights"]:
        out.append(f'<div class="insight"><span class="badge {_e(i["severity"])}">{_e(i["severity"])}</span>'
                   f'<span class="t">{_e(i["title"])}</span>'
                   + (f'<div class="d">{_e(i["detail"])}</div>' if i["detail"] else "")
                   + (f'<div class="a">→ {_e(i["suggested_action"])}</div>' if i["suggested_action"] else "") + "</div>")
    return "".join(out)


def _budgets(snap) -> str:
    """One bar per budget. The tick is where the month itself has got to, so a
    bar past the tick is spending faster than the month is passing."""
    summary = snap["budgets"]
    rows = summary["budgets"]
    if not rows:
        return ('<p class="muted">no budgets yet — ledger budget suggest, '
                'then ledger budget set &lt;category&gt; --amount 500</p>')
    out = []
    for b in rows:
        pct = b["percent"] if b["percent"] is not None else 100
        color = svg.PALETTE[3] if b["over_budget"] else (svg.PALETTE[1] if b["over_rate"] else svg.PALETTE[2])
        sub = f"{fmt(b['spent_cents'])} of {fmt(b['available_cents'])}"
        if b["carry_in_cents"]:
            sub += f" · {fmt(b['carry_in_cents'])} carried in"
        if b["over_budget"]:
            sub += f" · {fmt(b['spent_cents'] - b['available_cents'])} over"
        elif b["over_rate"]:
            sub += f" · running at {fmt(b['projected_cents'])} a month"
        out.append(f"<div><strong>{_e(b['category'])}</strong> "
                   f"<span class='muted'>{round(pct)}%</span>{svg.progress(min(pct, 100), color=color)}"
                   f"<div class='muted'>{_e(sub)}</div></div>")
    if summary["unbudgeted"]:
        named = ", ".join(f"{u['category']} {fmt(u['spent_cents'])}" for u in summary["unbudgeted"][:3])
        out.append(f"<p class='muted'>{_e(fmt(summary['unbudgeted_cents']))} of spending has no budget — "
                   f"{_e(named)}</p>")
    return "".join(out)


def _goals(snap) -> str:
    if not snap["goals"]:
        return '<p class="muted">no goals yet — ledger goals add &lt;name&gt; --target 5000 --by 2027-06-01 --account &lt;id&gt;</p>'
    out = []
    for g in snap["goals"]:
        pct = g["percent"] or 0
        if g["kind"] == "savings":
            color = svg.PALETTE[2] if g["on_track"] is not False else svg.PALETTE[3]
            sub = (f"{fmt(g['current_cents'])} of {fmt(g['target_cents'])}"
                   + (f" · target {g['target_date']}" if g["target_date"] else "")
                   + (f" · projected {g['projected_date']}" if g["projected_date"] else ""))
        else:
            color = svg.PALETTE[2] if g["on_track"] else svg.PALETTE[3]
            sub = f"{fmt(g['current_cents'])} of {fmt(g['target_cents'])} cap in {g['month']}"
        out.append(f"<div><strong>{_e(g['name'])}</strong> <span class='muted'>{pct}%</span>{svg.progress(pct, color=color)}"
                   f"<div class='muted'>{_e(sub)}</div></div>")
    return "".join(out)


def _upcoming(snap) -> str:
    if not snap["upcoming"]:
        return '<p class="muted">nothing recurring due in the next 30 days</p>'
    out = ["<table><tr><th>Date</th><th>What</th><th class='num'>Amount</th></tr>"]
    for r in snap["upcoming"]:
        out.append(f"<tr><td>{_e(epoch_to_date(r['next_expected']))}</td><td>{_e(r['label'])}</td><td class='num'>{_e(fmt(r['typical_amount_cents']))}</td></tr>")
    out.append(f"<tr><td></td><td><strong>total</strong></td><td class='num'><strong>{_e(fmt(snap['upcoming_total_cents']))}</strong></td></tr></table>")
    out.append(f"<p class='muted'>cash on hand {_e(fmt(snap['cash_cents']))}</p>")
    return "".join(out)


def _footer(snap) -> str:
    ls = snap["last_sync"]
    if ls is None:
        return "no sync yet"
    txt = f"last sync {ls['at']} ({'ok' if ls['ok'] else 'failed'})"
    if ls["errlist"]:
        txt += " · bridge reported: " + "; ".join(_e(json.dumps(e) if isinstance(e, dict) else str(e)) for e in ls["errlist"])
    if not snap["history_complete"]:
        txt += " · history still backfilling"
    return txt


def render(snap: dict) -> str:
    body = []
    body.append(f"<header><h1>Ledger</h1><span class='muted'>as of {_e(snap['as_of'])}</span>"
                f"<span class='muted'>net worth <strong>{_e(fmt(snap['net_worth_cents']))}</strong> · cash {_e(fmt(snap['cash_cents']))}"
                f" · liabilities {_e(fmt(snap['liabilities_cents']))}</span></header>")
    body.append('<div class="grid">')
    body.append(f'<section class="card wide"><h2>This month</h2>{_month_card(snap)}</section>')
    body.append(f'<section class="card"><h2>Accounts</h2>{_accounts(snap)}</section>')
    body.append(f'<section class="card"><h2>Cash flow</h2>{svg.grouped_bars(snap["cash_flow"], fmt=fmt)}</section>')
    body.append(f'<section class="card"><h2>Spending by category</h2>{_categories(snap)}</section>')
    body.append(f'<section class="card"><h2>Budgets · {_e(snap["budgets"]["month"])}</h2>{_budgets(snap)}</section>')
    body.append(f'<section class="card"><h2>Insights</h2>{_insights(snap)}</section>')
    body.append(f'<section class="card"><h2>Subscriptions · {_e(fmt(snap["subscriptions_monthly_cents"]))}/month</h2>'
                f'{_series_table(snap["subscriptions"], "no subscriptions detected yet")}</section>')
    body.append(f'<section class="card"><h2>Recurring bills</h2>{_series_table(snap["bills"], "no recurring bills detected yet")}</section>')
    body.append(f'<section class="card"><h2>Goals</h2>{_goals(snap)}</section>')
    body.append(f'<section class="card"><h2>Due in the next 30 days</h2>{_upcoming(snap)}</section>')
    body.append("</div>")
    body.append(f"<footer>{_footer(snap)}</footer>")
    snapshot_json = json.dumps(snap, default=str).replace("</", "<\\/")
    return (_TEMPLATE.read_text()
            .replace("__TITLE__", f"Ledger — {_e(snap['as_of'])}")
            .replace("__BODY__", "\n".join(body))
            .replace("__SNAPSHOT__", snapshot_json))


def write(conn: sqlite3.Connection, path: str | os.PathLike | None = None, now: int | None = None) -> Path:
    path = Path(path) if path else config.dashboard_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = render(build_snapshot(conn, now))
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".dashboard.", suffix=".html")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
