"""ledger command line.

Every command has --json for Claude and scripts. Exit codes: 0 ok, 1 error,
2 not set up (no credentials), 3 SimpleFIN request budget exhausted.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys

from ledger import __version__, categorize, config, credentials, db, reports, simplefin, sync
from ledger.money import epoch_to_date, fmt, month_of, parse_cents

EXIT_OK, EXIT_ERROR, EXIT_NOT_SET_UP, EXIT_BUDGET = 0, 1, 2, 3


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_ERROR):
        super().__init__(message)
        self.code = code


# --- output helpers ------------------------------------------------------

def emit(args, payload, human) -> None:
    if args.json:
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        human()


def table(rows: list[list[str]], headers: list[str], right: set[int] = frozenset()) -> None:
    if not rows:
        print("(none)")
        return
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))
    def line(cells):
        return "  ".join((str(c).rjust(w) if i in right else str(c).ljust(w)) for i, (c, w) in enumerate(zip(cells, widths)))
    print(line(headers))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line(r))


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def require_access_url() -> str:
    url = credentials.get_access_url()
    if not url:
        raise CliError("no SimpleFIN credentials. Run: ledger setup   (or export SIMPLEFIN_ACCESS_URL)", EXIT_NOT_SET_UP)
    return url


def open_db():
    return db.connect()


# --- commands ------------------------------------------------------------

def cmd_setup(args) -> int:
    """Claim a SimpleFIN setup token and store the access URL in Keychain."""
    if args.from_env:
        url = credentials.get_access_url()
        if not url:
            raise CliError(f"{credentials.ENV_VAR} is not set", EXIT_NOT_SET_UP)
    else:
        if credentials.source() == "keychain" and not args.force:
            raise CliError("credentials already stored. Re-run with --force to replace them")
        token = getpass.getpass("SimpleFIN setup token (input hidden): ")
        if not token.strip():
            raise CliError("no token entered")
        try:
            url = simplefin.claim(token)
        except simplefin.SimpleFinError as e:
            raise CliError(str(e))
    try:
        credentials.set_access_url(url)
    except credentials.CredentialError as e:
        raise CliError(str(e))
    host = simplefin.host_of(url)
    emit(args, {"stored": "keychain", "host": host},
         lambda: print(f"Stored SimpleFIN credentials for {host} in Keychain. Next: ledger sync"))
    return EXIT_OK


def cmd_sync(args) -> int:
    url = require_access_url()
    conn = open_db()
    try:
        results = sync.run(conn, url, max_requests=args.max_requests)
    except sync.BudgetExhausted as e:
        raise CliError(str(e), EXIT_BUDGET)
    except simplefin.SimpleFinError as e:
        raise CliError(str(e))
    errs = [e for r in results for e in r.errlist]
    for e in errs:
        warn(f"SimpleFIN: {e}")
    payload = {
        "runs": [r.as_dict() for r in results],
        "requests": sum(r.requests for r in results),
        "new": sum(r.tx_new for r in results),
        "updated": sum(r.tx_updated for r in results),
        "backfill_done": sync.backfill_done(conn),
        "requests_used_24h": sync.requests_last_24h(conn, db.now_epoch()),
        "errlist": errs,
    }
    if not args.no_dashboard:
        payload["dashboard"] = _maybe_dashboard(conn)
    if getattr(args, "export", False):
        from ledger import export
        payload["export"] = export.write(conn)

    def human():
        for r in results:
            print(f"{r.kind:<11} {epoch_to_date(r.start)} .. {epoch_to_date(r.end)}  "
                  f"{r.accounts} accounts, {r.tx_seen} seen, {r.tx_new} new, {r.tx_updated} updated")
        tail = "history complete" if payload["backfill_done"] else "more history arrives on the next sync"
        print(f"{payload['requests']} request(s); {payload['requests_used_24h']}/{sync.DAILY_CEILING} used today; {tail}")
        if payload.get("dashboard"):
            print(f"dashboard: {payload['dashboard']}")
    emit(args, payload, human)
    return EXIT_OK


def _maybe_dashboard(conn) -> str | None:
    try:
        from ledger import dashboard  # Phase 4
    except ImportError:
        return None
    return str(dashboard.write(conn))


def cmd_accounts(args) -> int:
    conn = open_db()
    if args.accounts_cmd == "set-kind":
        cur = conn.execute("UPDATE accounts SET kind = ?, kind_source = 'user' WHERE id = ?", (args.kind, args.id))
        conn.commit()
        if cur.rowcount == 0:
            raise CliError(f"no account with id {args.id}")
        emit(args, {"id": args.id, "kind": args.kind}, lambda: print(f"{args.id}: {args.kind}"))
        return EXIT_OK
    if args.accounts_cmd == "reclassify":
        changed = sync.reclassify_accounts(conn)
        emit(args, {"changed": changed},
             lambda: (table([[c["id"], c["name"], c["was"], c["kind"]] for c in changed],
                            ["ID", "ACCOUNT", "WAS", "NOW"]) if changed else None,
                      print(f"\n{len(changed)} account(s) reclassified")))
        return EXIT_OK
    if args.accounts_cmd == "hide":
        conn.execute("UPDATE accounts SET hidden = ? WHERE id = ?", (0 if args.show else 1, args.id))
        conn.commit()
        emit(args, {"id": args.id, "hidden": not args.show}, lambda: print("ok"))
        return EXIT_OK
    accts = reports.accounts(conn, include_hidden=args.all)
    nw = reports.net_worth(conn)

    def human():
        table([[a["id"], a["name"], a["kind"], fmt(a["balance_cents"], a["currency"]),
                fmt(a["available_cents"], a["currency"]) if a["available_cents"] is not None else "",
                epoch_to_date(a["balance_date"]) if a["balance_date"] else "", a["transactions"]] for a in accts],
              ["ID", "ACCOUNT", "KIND", "BALANCE", "AVAILABLE", "AS OF", "TX"], right={3, 4, 6})
        print(f"\nnet worth {fmt(nw['total_cents'])}  (assets {fmt(nw['assets_cents'])}, liabilities {fmt(nw['liabilities_cents'])})")
    emit(args, {"accounts": accts, "net_worth": {k: v for k, v in nw.items() if k != "accounts"}}, human)
    return EXIT_OK


def cmd_transactions(args) -> int:
    conn = open_db()
    rows = reports.transactions(
        conn, start=args.from_date, end=args.to_date, account=args.account, category=args.category,
        payee=args.payee, text=args.search, min_cents=parse_cents(args.min) if args.min else None,
        max_cents=parse_cents(args.max) if args.max else None, uncategorized=args.uncategorized,
        limit=args.limit)

    def human():
        table([[r["date"], r["account"] or r["account_id"], fmt(r["amount_cents"], r["currency"]),
                (r["category"] or "") + (" *" if r["pending"] else ""), r["description"][:48], r["id"]] for r in rows],
              ["DATE", "ACCOUNT", "AMOUNT", "CATEGORY", "DESCRIPTION", "ID"], right={2})
        print(f"\n{len(rows)} transaction(s); * = pending")
    emit(args, {"transactions": rows, "count": len(rows)}, human)
    return EXIT_OK


def cmd_categorize(args) -> int:
    conn = open_db()
    if args.categorize_cmd == "set":
        n = categorize.set_category(conn, args.ids, args.category, source=args.source)
        emit(args, {"updated": n, "category": args.category}, lambda: print(f"{n} transaction(s) -> {args.category}"))
        return EXIT_OK
    n = categorize.categorize(conn, only_uncategorized=not args.all)
    left = reports.uncategorized_payees(conn)

    def human():
        print(f"{n} transaction(s) categorized")
        if left:
            print("\nstill uncategorized (by payee):")
            table([[p["payee"], p["count"], fmt(p["net_cents"]), p["example"][:40]] for p in left],
                  ["PAYEE", "N", "NET", "EXAMPLE"], right={1, 2})
            print("\nassign one with: ledger rules add <payee> --category <name>")
    emit(args, {"categorized": n, "uncategorized_payees": left}, human)
    return EXIT_OK


def cmd_rules(args) -> int:
    conn = open_db()
    if args.rules_cmd == "add":
        try:
            rid = categorize.add_rule(conn, args.pattern, args.category, match_type=args.type, source=args.source)
        except ValueError as e:
            raise CliError(str(e))
        n = categorize.categorize(conn, only_uncategorized=False)
        emit(args, {"id": rid, "applied": n}, lambda: print(f"rule {rid} added; {n} transaction(s) recategorized"))
        return EXIT_OK
    if args.rules_cmd == "remove":
        if not categorize.remove_rule(conn, args.id):
            raise CliError(f"no rule with id {args.id}")
        emit(args, {"removed": args.id}, lambda: print("removed"))
        return EXIT_OK
    rules = categorize.list_rules(conn)
    emit(args, {"rules": rules},
         lambda: table([[r["id"], r["match_type"], r["pattern"], r["category"], r["source"], r["hits"]] for r in rules],
                       ["ID", "TYPE", "PATTERN", "CATEGORY", "SOURCE", "HITS"], right={0, 5}))
    return EXIT_OK


def cmd_report(args) -> int:
    conn = open_db()
    month = args.month or month_of(epoch_to_date(db.now_epoch()))
    rep = reports.monthly_report(conn, month)
    flow = reports.cash_flow(conn, args.months, month) if args.months > 1 else None

    def human():
        p = rep["previous"]
        print(f"{rep['month']}: income {fmt(rep['income_cents'])}  spending {fmt(rep['expense_cents'])}  "
              f"net {fmt(rep['net_cents'])}   (prev {p['month']}: spending {fmt(p['expense_cents'])})")
        if rep["fees_cents"]:
            print(f"fees & interest: {fmt(rep['fees_cents'])}")
        if rep["uncategorized"]:
            print(f"{rep['uncategorized']} uncategorized transaction(s)")
        print("\nby category")
        table([[c["key"], fmt(c["spent_cents"]), c["count"]] for c in rep["by_category"]],
              ["CATEGORY", "SPENT", "N"], right={1, 2})
        print("\ntop payees")
        table([[c["key"], fmt(c["spent_cents"]), c["count"]] for c in rep["top_payees"]],
              ["PAYEE", "SPENT", "N"], right={1, 2})
        if flow:
            print("\ncash flow")
            table([[m["month"], fmt(m["income_cents"]), fmt(m["expense_cents"]), fmt(m["net_cents"])] for m in flow],
                  ["MONTH", "INCOME", "SPENDING", "NET"], right={1, 2, 3})
    payload = dict(rep)
    if flow:
        payload["cash_flow"] = flow
    emit(args, payload, human)
    return EXIT_OK


def cmd_doctor(args) -> int:
    from ledger import doctor
    conn = open_db()
    results = doctor.checks(conn)

    def human():
        for r in results:
            mark = {"ok": "ok  ", "warn": "warn", "error": "FAIL"}[r["level"]]
            print(f"{mark}  {r['name']}: {r['detail']}")
    emit(args, {"checks": results, "problems": doctor.problems(results)}, human)
    return EXIT_OK if doctor.problems(results) == 0 else EXIT_ERROR


# --- parser --------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ledger", description="Personal budget tracker on SimpleFIN, local-first.")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--home", metavar="DIR", help="state directory (default ~/.ledger or $LEDGER_HOME)")
    p.add_argument("--version", action="version", version=f"ledger {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    s = sub.add_parser("setup", help="claim a SimpleFIN setup token and store the credentials")
    s.add_argument("--from-env", action="store_true", help=f"store the URL from {credentials.ENV_VAR} instead of claiming")
    s.add_argument("--force", action="store_true", help="replace stored credentials")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("sync", help="fetch new activity, then extend history while budget remains")
    s.add_argument("--max-requests", type=int, default=6, metavar="N", help="SimpleFIN requests this run may spend (default 6)")
    s.add_argument("--no-dashboard", action="store_true", help="skip regenerating the dashboard")
    s.add_argument("--export", action="store_true", help="also write the Cowork export (see: ledger export)")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("accounts", help="list accounts and net worth")
    s.add_argument("--all", action="store_true", help="include hidden accounts")
    ss = s.add_subparsers(dest="accounts_cmd")
    k = ss.add_parser("set-kind", help="override an account's kind")
    k.add_argument("id"); k.add_argument("kind", choices=["checking", "savings", "credit", "loan", "investment", "other"])
    ss.add_parser("reclassify", help="re-run the kind heuristic over every account you have not set by hand")
    h = ss.add_parser("hide", help="hide an account from reports")
    h.add_argument("id"); h.add_argument("--show", action="store_true", help="unhide instead")
    s.set_defaults(fn=cmd_accounts)

    s = sub.add_parser("transactions", help="search transactions")
    s.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    s.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", help="exclusive")
    s.add_argument("--account"); s.add_argument("--category"); s.add_argument("--payee")
    s.add_argument("--search", metavar="TEXT"); s.add_argument("--min", metavar="AMT"); s.add_argument("--max", metavar="AMT")
    s.add_argument("--uncategorized", action="store_true")
    s.add_argument("--limit", type=int, default=100)
    s.set_defaults(fn=cmd_transactions)

    s = sub.add_parser("categorize", help="apply rules and heuristics to uncategorized transactions")
    s.add_argument("--all", action="store_true", help="re-run on everything not set by hand")
    ss = s.add_subparsers(dest="categorize_cmd")
    st = ss.add_parser("set", help="set a category on specific transactions")
    st.add_argument("ids", nargs="+", metavar="TX_ID")
    st.add_argument("--category", required=True)
    st.add_argument("--source", default="user", choices=["user", "claude"])
    s.set_defaults(fn=cmd_categorize)

    s = sub.add_parser("rules", help="categorization rules")
    ss = s.add_subparsers(dest="rules_cmd")
    a = ss.add_parser("add"); a.add_argument("pattern"); a.add_argument("--category", required=True)
    a.add_argument("--type", default="payee", choices=["payee", "contains", "regex"])
    a.add_argument("--source", default="user", choices=["user", "claude"])
    r = ss.add_parser("remove"); r.add_argument("id", type=int)
    ss.add_parser("list")
    s.set_defaults(fn=cmd_rules)

    s = sub.add_parser("report", help="monthly income, spending and categories")
    s.add_argument("--month", metavar="YYYY-MM")
    s.add_argument("--months", type=int, default=1, help="also show cash flow over N months")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("doctor", help="check credentials, database, sync state and registrations")
    s.set_defaults(fn=cmd_doctor)

    return p


def register_extra(parser: argparse.ArgumentParser) -> None:
    """Later phases hang their subcommands here without touching this file's
    core. Each module exposes add_commands(subparsers)."""
    sub = None
    for action in parser._actions:  # noqa: SLF001 - argparse has no public accessor
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            sub = action
    for modname in ("ledger.insights.cli", "ledger.mcp_cli", "ledger.dashboard_cli", "ledger.schedule"):
        try:
            mod = __import__(modname, fromlist=["add_commands"])
        except ImportError:
            continue
        if hasattr(mod, "add_commands"):
            mod.add_commands(sub)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    register_extra(parser)
    args = parser.parse_args(argv)
    if args.home:
        config.set_home(args.home)
    if not getattr(args, "fn", None):
        parser.print_help()
        return EXIT_OK
    try:
        return args.fn(args)
    except CliError as e:
        print(f"error: {simplefin.redact(e)}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
