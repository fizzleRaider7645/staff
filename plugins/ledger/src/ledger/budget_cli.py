"""`ledger budget` — set caps, see where they stand, and get proposals.

Registered through cli.register_extra, so cli.py does not have to know.
"""
from __future__ import annotations

from ledger import budgets, db
from ledger.cli import EXIT_OK, CliError, emit, open_db, table
from ledger.money import epoch_to_date, fmt, month_of, parse_cents


def _mark(row) -> str:
    if row["over_budget"]:
        return "OVER"
    if row["over_rate"]:
        return "fast"
    return ""


def cmd_budget(args) -> int:
    conn = open_db()
    cmd = getattr(args, "budget_cmd", None)

    if cmd == "set":
        amount = parse_cents(args.amount)
        bid = budgets.set_budget(conn, args.category, abs(amount), start_month=args.from_month,
                                 rollover=not args.no_rollover, carry_cap_months=args.carry_cap,
                                 notes=args.notes)
        emit(args, {"budget_id": bid, "category": args.category, "amount_cents": abs(amount)},
             lambda: print(f"{args.category}: {fmt(abs(amount))} a month"
                           + ("" if not args.no_rollover else ", no rollover")))
        return EXIT_OK

    if cmd == "remove":
        n = budgets.remove_budget(conn, args.category)
        if not n:
            raise CliError(f"no budget for {args.category}")
        emit(args, {"removed": n, "category": args.category},
             lambda: print(f"removed {n} budget row(s) for {args.category}"))
        return EXIT_OK

    if cmd == "reset":
        month = args.month or month_of(epoch_to_date(db.now_epoch()))
        budgets.adjust(conn, args.category, month, "reset", note=args.note)
        emit(args, {"category": args.category, "month": month, "kind": "reset"},
             lambda: print(f"{args.category}: carry cleared for {month}"))
        return EXIT_OK

    if cmd == "suggest":
        proposals = budgets.suggest(conn, months=args.months)
        if args.apply:
            applied = [p for p in proposals if p["confidence"] in ("high", "medium")]
            for p in applied:
                budgets.set_budget(conn, p["category"], p["suggested_cents"], basis=p["basis"])
            emit(args, {"applied": applied, "skipped": len(proposals) - len(applied)},
                 lambda: print(f"set {len(applied)} budget(s); skipped "
                               f"{len(proposals) - len(applied)} with no usable history"))
            return EXIT_OK

        def human():
            table([[p["category"], fmt(p["suggested_cents"]), p["basis"], p["confidence"], p["note"][:46]]
                   for p in proposals], ["CATEGORY", "SUGGESTED", "BASIS", "CONFIDENCE", "WHY"], right={1})
            weak = [p for p in proposals if p["confidence"] in ("low", "none")]
            if weak:
                print(f"\n{len(weak)} of {len(proposals)} rest on incomplete history and are guesses.")
            print("accept the usable ones: ledger budget suggest --apply")
        emit(args, {"proposals": proposals}, human)
        return EXIT_OK

    # Default: where everything stands.
    s = budgets.summary(conn, args.month)

    def human():
        if not s["budgets"]:
            print("no budgets set. propose some with: ledger budget suggest")
        else:
            table([[b["category"], fmt(b["amount_cents"]),
                    fmt(b["carry_in_cents"]) if b["carry_in_cents"] else "",
                    fmt(b["available_cents"]), fmt(b["spent_cents"]), fmt(b["remaining_cents"]),
                    fmt(b["projected_cents"]), _mark(b)] for b in s["budgets"]],
                  ["CATEGORY", "BUDGET", "CARRY", "AVAILABLE", "SPENT", "LEFT", "PROJECTED", ""],
                  right={1, 2, 3, 4, 5, 6})
            print(f"\n{s['month']}: {fmt(s['spent_cents'])} of {fmt(s['available_cents'])} available"
                  f"  ({s['over_count']} over budget)")
        if s["unbudgeted"]:
            print(f"\nspending with no budget — {fmt(s['unbudgeted_cents'])}")
            table([[u["category"], fmt(u["spent_cents"])] for u in s["unbudgeted"][:10]],
                  ["CATEGORY", "SPENT"], right={1})
    emit(args, s, human)
    return EXIT_OK


def add_commands(sub) -> None:
    s = sub.add_parser("budget", help="monthly caps per category, with rollover")
    s.add_argument("--month", metavar="YYYY-MM")
    ss = s.add_subparsers(dest="budget_cmd")

    a = ss.add_parser("set", help="set a category's monthly cap")
    a.add_argument("category")
    a.add_argument("--amount", required=True, metavar="AMT")
    a.add_argument("--no-rollover", action="store_true", help="do not carry unspent money forward")
    a.add_argument("--carry-cap", type=float, default=budgets.DEFAULT_CARRY_CAP_MONTHS,
                   metavar="N", help="stop positive carry at N months of budget (default 3)")
    a.add_argument("--from", dest="from_month", metavar="YYYY-MM", help="first month it applies")
    a.add_argument("--notes")

    r = ss.add_parser("remove", help="drop a category's budget")
    r.add_argument("category")

    z = ss.add_parser("reset", help="clear a category's carry for a month")
    z.add_argument("category")
    z.add_argument("--month", metavar="YYYY-MM")
    z.add_argument("--note")

    g = ss.add_parser("suggest", help="propose budgets from history, with the basis for each")
    g.add_argument("--months", type=int, default=3, help="how many complete months to draw on")
    g.add_argument("--apply", action="store_true", help="set the proposals that have usable history")

    s.set_defaults(fn=cmd_budget)
