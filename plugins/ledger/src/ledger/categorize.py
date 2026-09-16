"""Assign categories.

Order of authority: an explicit rule (user > claude > import > heuristic),
then the service catalog's default, then keyword heuristics. A category a
person set by hand is never overwritten by anything automatic.
"""
from __future__ import annotations

import re
import sqlite3

from ledger import catalog, db
from ledger.normalize import payee_key

SOURCE_RANK = {"user": 0, "claude": 1, "import": 2, "heuristic": 3, "rule": 3}

FEE_KEYWORDS = ("OVERDRAFT", "LATE FEE", "ANNUAL FEE", "MONTHLY FEE", "SERVICE FEE",
                "INTEREST CHARGE", "FINANCE CHARGE", "FOREIGN TRANSACTION FEE", "ATM FEE",
                "MAINTENANCE FEE", "RETURNED ITEM", "NSF FEE", "INTEREST CHARGED")
INCOME_KEYWORDS = ("PAYROLL", "DIRECT DEP", "DIRECTDEP", "SALARY", "PAYCHECK", "PAY DAY", "PAYDAY", "DEPOSIT",
                   "INTEREST PAID", "INTEREST PAYMENT", "DIVIDEND", "TAX REFUND", "IRS TREAS",
                   "REFUND", "REIMBURSE")
TRANSFER_KEYWORDS = ("TRANSFER", "XFER", "ZELLE", "VENMO", "CASH APP", "CASHAPP",
                     "ONLINE PAYMENT THANK YOU", "AUTOPAY PAYMENT", "PAYMENT - THANK YOU",
                     "PAYMENT THANK YOU", "AUTOMATIC PAYMENT", "CREDIT CARD PAYMENT",
                     "EPAYMENT", "E-PAYMENT", "MOBILE PAYMENT", "INTERNET PAYMENT")

KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Groceries", ("SAFEWAY", "TRADER JOE", "WHOLE FOODS", "WHOLEFDS", "KROGER", "ALBERTSONS",
                   "PUBLIX", "WEGMANS", "H-E-B", "HEB ", "ALDI", "SPROUTS", "RALPHS", "VONS",
                   "GROCERY", "MARKET", "FOOD LION", "STOP & SHOP", "GIANT", "MEIJER", "WINCO",
                   "LUCKY", "INSTACART")),
    ("Dining", ("RESTAURANT", "CAFE", "COFFEE", "PIZZA", "DOORDASH", "UBER EATS", "UBEREATS",
                "GRUBHUB", "STARBUCKS", "CHIPOTLE", "MCDONALD", "TACO", "BURGER", "SUSHI",
                "BAKERY", "DELI", "KITCHEN", "GRILL", "BISTRO", "DINER", "BAR ", "PUB ",
                "BREWING", "BREWERY", "PANERA", "SUBWAY", "WENDY", "CHICK-FIL", "DUNKIN",
                "PEET", "BLUE BOTTLE", "PHILZ", "SWEETGREEN", "CAVA", "EATS", "RAMEN",
                "NOODLE", "THAI", "PHO ", "BBQ", "STEAK")),
    ("Transportation", ("UBER", "LYFT", "PARKING", "TOLL", "TRANSIT", "MTA", "BART", "METRO",
                        "CALTRAIN", "AMTRAK", "PARKMOBILE", "CLIPPER", "DMV", "CAR WASH",
                        "AUTO REPAIR", "JIFFY LUBE", "TIRE", "AUTOZONE", "O'REILLY")),
    ("Gas", ("SHELL", "CHEVRON", "EXXON", "MOBIL", "ARCO", "76 ", "CIRCLE K", "VALERO",
             "SUNOCO", "MARATHON", "SPEEDWAY", "WAWA", "FUEL", "GAS STATION", "COSTCO GAS",
             "BP#", "BP ", "TEXACO", "CITGO", "PHILLIPS 66")),
    ("Utilities", ("PG&E", "PGE", "PACIFIC GAS", "ELECTRIC", "EDISON", "CON ED", "DUKE ENERGY",
                   "WATER", "SEWER", "UTILITY", "UTILITIES", "INTERNET", "WIRELESS", "ENERGY",
                   "POWER", "SANITATION", "WASTE MANAGEMENT", "RECOLOGY")),
    ("Housing", ("RENT", "MORTGAGE", "HOA ", "PROPERTY MGMT", "PROPERTY MANAGEMENT",
                 "APARTMENTS", "REALTY", "LEASING")),
    ("Health", ("PHARMACY", "CVS", "WALGREENS", "RITE AID", "MEDICAL", "DENTAL", "DENTIST",
                "CLINIC", "HOSPITAL", "OPTOMETRY", "OPTICAL", "PHYSICIAN", "THERAPY",
                "URGENT CARE", "KAISER", "LABCORP", "QUEST DIAG", "GYM", "FITNESS", "YOGA",
                "CROSSFIT", "ORTHO")),
    ("Insurance", ("INSURANCE", "GEICO", "STATE FARM", "PROGRESSIVE", "ALLSTATE", "FARMERS INS",
                   "LIBERTY MUTUAL", "USAA", "LEMONADE", "METLIFE", "AETNA", "ANTHEM",
                   "BLUE CROSS", "BLUE SHIELD", "CIGNA", "UNITEDHEALTH")),
    ("Travel", ("AIRLINE", "AIRLINES", "UNITED", "DELTA", "AMERICAN AIR", "SOUTHWEST", "JETBLUE",
                "ALASKA AIR", "SPIRIT", "FRONTIER", "HOTEL", "MARRIOTT", "HILTON", "HYATT",
                "AIRBNB", "VRBO", "HERTZ", "AVIS", "ENTERPRISE RENT", "BOOKING.COM", "EXPEDIA",
                "KAYAK", "PRICELINE", "RESORT", "INN ", "MOTEL", "TSA", "LOUNGE")),
    ("Shopping", ("AMAZON", "AMZN", "TARGET", "WALMART", "BEST BUY", "BESTBUY", "IKEA",
                  "HOME DEPOT", "LOWES", "LOWE'S", "COSTCO", "NORDSTROM", "MACY", "GAP",
                  "OLD NAVY", "H&M", "ZARA", "UNIQLO", "NIKE", "ADIDAS", "REI", "APPLE STORE",
                  "APPLE.COM", "ETSY", "EBAY", "WAYFAIR", "CRATE", "WILLIAMS-SONOMA",
                  "SEPHORA", "ULTA", "TJ MAXX", "TJMAXX", "MARSHALLS", "ROSS", "DOLLAR",
                  "STAPLES", "OFFICE DEPOT", "MICRO CENTER", "SHOP")),
    ("Entertainment", ("CINEMA", "THEATRE", "THEATER", "AMC", "REGAL", "TICKETMASTER",
                       "STUBHUB", "STEAM", "STEAMGAMES", "NINTENDO", "PLAYSTATION", "XBOX",
                       "CONCERT", "MUSEUM", "ZOO", "AQUARIUM", "BOWLING", "GOLF", "SKI",
                       "SPOTIFY", "NETFLIX", "HULU")),
    ("Personal Care", ("SALON", "BARBER", "HAIR", "SPA ", "MASSAGE", "NAILS", "LAUNDRY",
                       "DRY CLEAN", "CLEANERS")),
    ("Education", ("TUITION", "UNIVERSITY", "COLLEGE", "UDEMY", "COURSERA", "SKILLSHARE",
                   "MASTERCLASS", "SCHOOL", "BOOKSTORE", "STUDENT LOAN", "NAVIENT", "NELNET",
                   "SALLIE MAE", "MOHELA")),
    ("Gifts & Donations", ("DONATION", "CHARITY", "GOFUNDME", "RED CROSS", "UNICEF",
                           "FOUNDATION", "CHURCH", "TEMPLE", "MOSQUE", "SYNAGOGUE", "WIKIMEDIA")),
    ("Pets", ("PETCO", "PETSMART", "CHEWY", "VETERINARY", "VET ", "ANIMAL HOSPITAL", "PET ")),
    ("Kids", ("DAYCARE", "CHILDCARE", "PRESCHOOL", "TOYS", "BABY", "PEDIATRIC")),
    ("Taxes", ("IRS", "TAX PAYMENT", "FRANCHISE TAX", "DEPT OF REVENUE", "TURBOTAX", "H&R BLOCK",
               "PROPERTY TAX", "TAX COLLECTOR")),
    ("Cash & ATM", ("ATM", "CASH WITHDRAWAL", "WITHDRAWAL", "CHECK ")),
    ("Investments", ("VANGUARD", "FIDELITY", "SCHWAB", "ROBINHOOD", "BETTERMENT", "WEALTHFRONT",
                     "E*TRADE", "ETRADE", "COINBASE", "ACORNS", "401K", "IRA ", "BROKERAGE")),
    ("Business", ("FEDEX", "UPS ", "USPS", "SHIPPING", "SQUARESPACE", "GODADDY", "NAMECHEAP",
                  "HEROKU", "AWS", "AMAZON WEB SERVICES", "DIGITALOCEAN", "VERCEL",
                  "CLOUDFLARE", "GOOGLE CLOUD", "LINKEDIN", "UPWORK")),
]


def category_id(conn: sqlite3.Connection, name: str, create: bool = False, kind: str = "expense") -> int | None:
    """Resolve a category by name or alias, case-insensitive."""
    if not name:
        return None
    row = conn.execute("SELECT id FROM categories WHERE lower(name) = lower(?)", (name,)).fetchone()
    if row:
        return row["id"]
    for r in conn.execute("SELECT id, aliases_json FROM categories"):
        import json
        if any(a.lower() == name.lower() for a in json.loads(r["aliases_json"])):
            return r["id"]
    if create:
        cur = conn.execute("INSERT INTO categories (name, kind) VALUES (?, ?)", (name, kind))
        return cur.lastrowid
    return None


def category_name(conn: sqlite3.Connection, cid: int | None) -> str | None:
    if cid is None:
        return None
    row = conn.execute("SELECT name FROM categories WHERE id = ?", (cid,)).fetchone()
    return row["name"] if row else None


# --- rules -------------------------------------------------------------

def load_rules(conn: sqlite3.Connection) -> list[dict]:
    rules = db.rows(conn, "SELECT * FROM rules")
    rules.sort(key=lambda r: (SOURCE_RANK.get(r["source"], 9), -r["priority"], r["id"]))
    for r in rules:
        if r["match_type"] == "regex":
            try:
                r["_rx"] = re.compile(r["pattern"], re.I)
            except re.error:
                r["_rx"] = None
    return rules


def rule_matches(rule: dict, description: str, key: str) -> bool:
    mt = rule["match_type"]
    if mt == "payee":
        return key.lower() == rule["pattern"].lower()
    if mt == "contains":
        return rule["pattern"].lower() in (description or "").lower()
    if mt == "regex":
        rx = rule.get("_rx")
        return bool(rx and rx.search(description or ""))
    return False


def add_rule(conn: sqlite3.Connection, pattern: str, category: str, match_type: str = "payee",
             source: str = "user", priority: int = 0, now: int | None = None) -> int:
    if match_type not in ("payee", "contains", "regex"):
        raise ValueError(f"match_type must be payee, contains or regex, not {match_type!r}")
    if match_type == "regex":
        re.compile(pattern)
    cid = category_id(conn, category, create=(source in ("user", "claude", "import")))
    if cid is None:
        raise ValueError(f"unknown category: {category}")
    cur = conn.execute(
        "INSERT INTO rules (match_type, pattern, category_id, source, priority, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (match_type, pattern, cid, source, priority, now or db.now_epoch()),
    )
    conn.commit()
    return cur.lastrowid


def remove_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    cur = conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    return cur.rowcount > 0


def list_rules(conn: sqlite3.Connection) -> list[dict]:
    return db.rows(conn, """
        SELECT r.id, r.match_type, r.pattern, c.name AS category, r.source, r.priority, r.hits, r.created_at
        FROM rules r JOIN categories c ON c.id = r.category_id
        ORDER BY r.source, r.priority DESC, r.id""")


# --- heuristics --------------------------------------------------------

def heuristic_category(description: str, amount_cents: int, key: str | None = None) -> str | None:
    desc = (description or "").upper()
    svc = catalog.match_service(desc)
    if any(k in desc for k in FEE_KEYWORDS):
        return "Fees & Interest"
    if any(k in desc for k in TRANSFER_KEYWORDS):
        return "Transfer"
    if amount_cents > 0 and any(k in desc for k in INCOME_KEYWORDS):
        return "Income"
    if svc and svc.get("category"):
        return svc["category"]
    for name, keywords in KEYWORDS:
        if any(k in desc for k in keywords):
            return name
    if amount_cents > 0 and ("INTEREST" in desc or "CREDIT" in desc):
        return "Income"
    return None


def decide(conn: sqlite3.Connection, rules: list[dict], description: str, key: str,
           amount_cents: int) -> tuple[int | None, str | None, dict | None]:
    """(category_id, source, matching_rule) for one transaction."""
    for rule in rules:
        if rule_matches(rule, description, key):
            return rule["category_id"], rule["source"] if rule["source"] != "heuristic" else "rule", rule
    name = heuristic_category(description, amount_cents, key)
    if name:
        return category_id(conn, name), "heuristic", None
    return None, None, None


def categorize(conn: sqlite3.Connection, *, only_uncategorized: bool = True,
               include_user: bool = False, ids: list[str] | None = None) -> int:
    """Run rules and heuristics. Returns how many rows changed."""
    rules = load_rules(conn)
    where = ["removed_at IS NULL"]
    params: list = []
    if ids:
        where.append("id IN (%s)" % ",".join("?" * len(ids)))
        params.extend(ids)
    elif only_uncategorized:
        where.append("category_id IS NULL")
    if not include_user:
        where.append("(category_source IS NULL OR category_source NOT IN ('user','claude'))")
    changed = 0
    for row in db.rows(conn, "SELECT id, description, payee_key, amount_cents, category_id FROM transactions WHERE " + " AND ".join(where), params):
        key = row["payee_key"] or payee_key(row["description"])
        cid, source, rule = decide(conn, rules, row["description"], key, row["amount_cents"])
        if cid is None or cid == row["category_id"]:
            continue
        conn.execute("UPDATE transactions SET category_id = ?, category_source = ? WHERE id = ?",
                     (cid, source, row["id"]))
        if rule:
            conn.execute("UPDATE rules SET hits = hits + 1 WHERE id = ?", (rule["id"],))
        changed += 1
    changed += pair_transfers(conn)
    conn.commit()
    return changed


def set_category(conn: sqlite3.Connection, tx_ids: list[str], category: str, source: str = "user") -> int:
    cid = category_id(conn, category, create=True)
    n = 0
    for tid in tx_ids:
        cur = conn.execute("UPDATE transactions SET category_id = ?, category_source = ? WHERE id = ?",
                           (cid, source, tid))
        n += cur.rowcount
    conn.commit()
    return n


def pair_transfers(conn: sqlite3.Connection, days: int = 3) -> int:
    """An outflow in one account matched by an equal inflow in another within
    a few days is money moving, not money spent."""
    transfer = category_id(conn, "Transfer")
    window = days * 86400
    candidates = db.rows(conn, """
        SELECT id, account_id, posted, amount_cents, category_source FROM transactions
        WHERE removed_at IS NULL AND pending = 0
          AND (category_id IS NULL OR category_source IN ('heuristic', 'rule'))
          AND (category_id IS NULL OR category_id != ?)
        ORDER BY posted""", (transfer,))
    by_amount: dict[int, list[dict]] = {}
    for c in candidates:
        by_amount.setdefault(c["amount_cents"], []).append(c)
    changed = 0
    used: set[str] = set()
    for c in candidates:
        if c["id"] in used or c["amount_cents"] >= 0:
            continue
        for other in by_amount.get(-c["amount_cents"], []):
            if other["id"] in used or other["account_id"] == c["account_id"]:
                continue
            if abs(other["posted"] - c["posted"]) <= window:
                for tid in (c["id"], other["id"]):
                    conn.execute("UPDATE transactions SET category_id = ?, category_source = 'heuristic' WHERE id = ?",
                                 (transfer, tid))
                    used.add(tid)
                changed += 2
                break
    return changed
