"""Phase 2 subcommands: subscriptions, insights, goals."""
from __future__ import annotations

from ledger import db, goals, insights, recurring
from ledger.cli import EXIT_OK, CliError, emit, open_db, table
from ledger.money import epoch_to_date, fmt, parse_cents


def cmd_subscriptions(args) -> int:
    conn = open_db()
    now = db.now_epoch()
    sub = getattr(args, "subs_cmd", None)
    if sub in ("ignore", "unignore", "label", "mark"):
        kwargs = {}
        if sub == "ignore":
            kwargs["status"] = "ignored"
        elif sub == "unignore":
            kwargs["status"] = ""
        elif sub == "label":
            kwargs["label"] = args.label
        elif sub == "mark":
            kwargs["is_subscription"] = args.subscription
        if not recurring.set_override(conn, args.id, now=now, **kwargs):
            raise CliError(f"no series with id {args.id}")
        emit(args, {"id": args.id, **kwargs}, lambda: print("ok"))
        return EXIT_OK
    if args.redetect or conn.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 0:
        recurring.redetect(conn, now)
    rows = recurring.roster(conn, include_lapsed=args.all, include_ignored=args.all,
                            subscriptions_only=not args.all and not args.bills)
    total = sum(r["monthly_cents"] for r in rows if r["status"] == "active" and r["is_subscription"])

    def human():
        table([[r["id"], r["label"], r["cadence"], fmt(r["typical_amount_cents"]), fmt(r["monthly_cents"]),
                epoch_to_date(r["next_expected"]) if r["next_expected"] else "", r["status"],
                "sub" if r["is_subscription"] else "bill", r["account"] or ""] for r in rows],
              ["ID", "NAME", "CADENCE", "AMOUNT", "PER MONTH", "NEXT", "STATUS", "KIND", "ACCOUNT"], right={3, 4})
        print(f"\n{len(rows)} series; active subscriptions {fmt(total)}/month ({fmt(total * 12)}/year)")
    emit(args, {"series": rows, "subscriptions_monthly_cents": total}, human)
    return EXIT_OK


def cmd_insights(args) -> int:
    conn = open_db()
    if getattr(args, "insights_cmd", None) == "dismiss":
        insights.dismiss(conn, args.key)
        emit(args, {"dismissed": args.key}, lambda: print("dismissed"))
        return EXIT_OK
    if getattr(args, "insights_cmd", None) == "undismiss":
        ok = insights.undismiss(conn, args.key)
        emit(args, {"undismissed": args.key, "found": ok}, lambda: print("ok" if ok else "not dismissed"))
        return EXIT_OK
    found = insights.run_all(conn, kinds=args.kind or None, min_severity=args.min_severity, include_dismissed=args.all)

    def human():
        if not found:
            print("nothing to report")
        for i in found:
            print(f"[{i.severity}] {i.title}")
            if i.detail:
                print(f"    {i.detail}")
            if i.suggested_action:
                print(f"    -> {i.suggested_action}")
            print(f"    key: {i.key}")
    emit(args, {"insights": [i.as_dict() for i in found], "count": len(found)}, human)
    return EXIT_OK


def cmd_goals(args) -> int:
    conn = open_db()
    sub = getattr(args, "goals_cmd", None) or "list"
    if sub == "add":
        try:
            gid = goals.add(conn, args.name, parse_cents(args.target), target_date=args.by, account_id=args.account,
                            category=args.category, from_now=args.from_now, notes=args.notes)
        except ValueError as e:
            raise CliError(str(e))
        emit(args, {"id": gid}, lambda: print(f"goal {gid} added"))
        return EXIT_OK
    if sub == "remove":
        if not goals.remove(conn, args.id):
            raise CliError(f"no goal with id {args.id}")
        emit(args, {"removed": args.id}, lambda: print("removed"))
        return EXIT_OK
    rows = goals.progress(conn)

    def human():
        for g in rows:
            if g["kind"] == "savings":
                proj = g["projected_date"] or "n/a"
                flag = "" if g["on_track"] is None else (" on track" if g["on_track"] else " BEHIND")
                print(f"[{g['id']}] {g['name']}: {fmt(g['current_cents'])} of {fmt(g['target_cents'])} ({g['percent']}%)"
                      f" by {g['target_date'] or 'no date'}; projected {proj}{flag}")
            else:
                print(f"[{g['id']}] {g['name']}: {g['category']} {fmt(g['current_cents'])} of {fmt(g['target_cents'])} cap"
                      f" in {g['month']} ({g['percent']}%){'' if g['on_track'] else ' OVER'}")
        if not rows:
            print("no goals. add one: ledger goals add <name> --target 5000 --by 2027-06-01 --account <id>")
    emit(args, {"goals": rows}, human)
    return EXIT_OK


def add_commands(sub) -> None:
    s = sub.add_parser("subscriptions", help="recurring charges: subscriptions and bills")
    s.add_argument("--all", action="store_true", help="include bills, lapsed and ignored series")
    s.add_argument("--bills", action="store_true", help="include recurring bills, not just subscriptions")
    s.add_argument("--redetect", action="store_true", help="re-run detection first")
    ss = s.add_subparsers(dest="subs_cmd")
    for name in ("ignore", "unignore"):
        p = ss.add_parser(name); p.add_argument("id")
    p = ss.add_parser("label"); p.add_argument("id"); p.add_argument("label")
    p = ss.add_parser("mark"); p.add_argument("id")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--subscription", dest="subscription", action="store_true")
    g.add_argument("--not-subscription", dest="subscription", action="store_false")
    s.set_defaults(fn=cmd_subscriptions)

    s = sub.add_parser("insights", help="savings opportunities and warnings")
    s.add_argument("--kind", action="append", help="only these kinds (repeatable)")
    s.add_argument("--min-severity", default="info", choices=["info", "notice", "warn", "alert"])
    s.add_argument("--all", action="store_true", help="include dismissed")
    ss = s.add_subparsers(dest="insights_cmd")
    p = ss.add_parser("dismiss"); p.add_argument("key")
    p = ss.add_parser("undismiss"); p.add_argument("key")
    s.set_defaults(fn=cmd_insights)

    s = sub.add_parser("goals", help="savings goals and spending caps")
    ss = s.add_subparsers(dest="goals_cmd")
    p = ss.add_parser("add"); p.add_argument("name"); p.add_argument("--target", required=True, metavar="AMT")
    p.add_argument("--by", metavar="YYYY-MM-DD"); p.add_argument("--account", metavar="ID")
    p.add_argument("--category", metavar="NAME"); p.add_argument("--from-now", action="store_true",
                                                                  help="count only what is saved from today")
    p.add_argument("--notes")
    p = ss.add_parser("remove"); p.add_argument("id", type=int)
    ss.add_parser("list")
    s.set_defaults(fn=cmd_goals)
