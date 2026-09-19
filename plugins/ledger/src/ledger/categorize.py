"""Assign categories.

Order of authority: an explicit rule (user > claude > import > heuristic),
then the service catalog's default, then keyword heuristics. A category a
person set by hand is never overwritten by anything automatic.
"""
from __future__ import annotations

import re
import sqlite3

from ledger import catalog, db, match
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
                     "EPAYMENT", "E-PAYMENT", "MOBILE PAYMENT", "INTERNET PAYMENT",
                     "ELECTRONIC PAYMENT",
                     # Banks abbreviate "payment" as often as they spell it.
                     "AUTOPAY PYMT", "MOBILE PYMT", "ONLINE PYMT", "PYMT THANK",
                     # Borrowed money arriving is not income.
                     # "DISB" also catches the abbreviated form banks use,
                     # e.g. "ACH: SOFI PL DISB".
                     "DISB", "LOAN PROCEEDS", "LOAN ADVANCE")
# Paying a card or lender that is not connected to the ledger. The purchases
# behind it are invisible, so calling it a transfer would delete the spending
# from the record entirely; it stays an expense until the other side shows up,
# at which point pair_transfers reclassifies both halves.
CARD_PAYMENT_KEYWORDS = ("APPLECARD", "GSBANK", "BARCLAYCARD", "BILT CARD", "BILT REWARDS",
                         "CARDMEMBER SERV", "CHASE CREDIT CRD", "CITI AUTOPAY", "CITI CARD",
                         "CITICARD", "AMEX EPAYMENT", "DISCOVER E-PAYMENT", "BK OF AMER CRD",
                         "WF CREDIT CARD", "COMENITY", "BREAD FINANCIAL")

# Moving money between your own accounts. Banks write these plainly — SoFi
# says "Withdrawal: To Checking - 9538" — but the words they use are words a
# spending category already claims, so WITHDRAWAL was filing $6,208 of internal
# movement under Cash & ATM and DEPOSIT was calling the other half income. The
# shape has to match *and* the descriptor has to name an account you hold,
# which no merchant descriptor does.
TRANSFER_SHAPE = re.compile(
    r"^\s*(?:WITHDRAWAL|DEPOSIT|OVERDRAFT|TRANSFER)\s*:"
    r"|\b(?:TO|FROM)\s+(?:MY\s+)?(?:CHECKING|SAVINGS)\b"
    r"|\b(?:CHECKING|SAVINGS)\s+BALANCE\b", re.I)
# A "vault" is a bucket inside a SoFi account, never a merchant.
VAULT_SHAPE = re.compile(r"\bVAULT\b", re.I)

# Delivery platforms are a channel, not a merchant: the shop is in the rest of
# the descriptor. Left alone, DOORDASH files Home Depot and Best Buy as Dining.
DELIVERY_PREFIX = re.compile(
    r"^\s*(?:DD\s*\*?\s*DOORDASH|DOORDASH\s*\*?|UBER\s*\*?\s*EATS|UBEREATS"
    r"|GRUBHUB\s*\*?|INSTACART\s*\*?|SEAMLESS\s*\*?|POSTMATES\s*\*?)\s*", re.I)
# What a delivery order is when the shop cannot be identified.
DELIVERY_DEFAULT = "Dining"

KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Groceries", ("SAFEWAY", "TRADER JOE", "WHOLE FOODS", "WHOLEFDS", "KROGER", "ALBERTSONS",
                   "PUBLIX", "WEGMANS", "H-E-B", "HEB", "ALDI", "SPROUTS", "RALPHS", "VONS",
                   "GROCERY", "MARKET", "FOOD LION", "STOP & SHOP", "GIANT", "GIANT EAGLE",
                   "MEIJER", "WINCO",
                   "LUCKY", "INSTACART", "SAM'S CLUB", "SAMS CLUB", "SAMSCLUB",
                   "BJ'S WHOLESALE", "BJS WHOLESALE")),
    ("Dining", ("RESTAURANT", "CAFE", "COFFEE", "PIZZA", "DOORDASH", "UBER EATS", "UBEREATS",
                "GRUBHUB", "STARBUCKS", "CHIPOTLE", "MCDONALD", "TACO", "BURGER", "SUSHI",
                "BAKERY", "DELI", "KITCHEN", "GRILL", "BISTRO", "DINER", "BAR", "PUB",
                "BREWING", "BREWERY", "PANERA", "SUBWAY", "WENDY", "WENDYS", "WENDY'S",
                "CHICK-FIL", "DUNKIN",
                "PEET", "BLUE BOTTLE", "PHILZ", "SWEETGREEN", "CAVA", "EATS", "RAMEN",
                "NOODLE", "THAI", "PHO", "BBQ", "STEAK", "ROADHOUSE", "DENNY",
                "CHILI'S", "ICE CREAM", "CREAMERY", "JENI'S", "LIQUOR", "SPIRITS",
                "BEER DIST", "TAVERN", "SALOON")),
    ("Transportation", ("UBER", "LYFT", "PARKING", "TOLL", "TRANSIT", "MTA", "BART", "METRO",
                        "CALTRAIN", "AMTRAK", "PARKMOBILE", "CLIPPER", "DMV", "CAR WASH",
                        "AUTO REPAIR", "JIFFY LUBE", "TIRE", "AUTOZONE", "O'REILLY",
                        "AUTO DETAIL", "AUTO DETAILI", "DETAILING", "U-HAUL", "UHAUL", "TOYOTA",
                        "HONDA FINANCIAL", "FORD CREDIT", "GM FINANCIAL", "VW CREDIT",
                        "NISSAN MOTOR ACCEPT", "CHRYSLER CAPITAL", "ALLY AUTO",
                        "AUTO LEASE", "CARMAX", "CARVANA")),
    ("Gas", ("SHELL", "CHEVRON", "EXXON", "MOBIL", "ARCO", "76", "CIRCLE K", "VALERO",
             "SUNOCO", "MARATHON", "SPEEDWAY", "WAWA", "FUEL", "GAS STATION", "COSTCO GAS",
             "BP#", "BP", "TEXACO", "CITGO", "PHILLIPS 66", "GET GO", "GETGO",
             "GAS N GO", "SHEETZ", "RUTTER", "TURKEY HILL", "QUIKTRIP", "KWIK")),
    ("Utilities", ("PG&E", "PGE", "PACIFIC GAS", "ELECTRIC", "EDISON", "CON ED", "DUKE ENERGY",
                   "WATER", "SEWER", "UTILITY", "UTILITIES", "INTERNET", "WIRELESS", "ENERGY",
                   "POWER", "SANITATION", "WASTE MANAGEMENT", "RECOLOGY", "DUQUESNE",
                   "SIMPLE MOBILE", "SIMPLEMOBILE",
                   "PPL ELECTRIC", "FIRSTENERGY", "NATIONAL GRID", "DOMINION ENERGY",
                   "AMEREN", "XCEL", "PECO", "COMED", "EVERSOURCE", "NICOR",
                   "COLUMBIA GAS", "NATURAL GAS", "GAS COMPANY")),
    ("Housing", ("RENT", "MORTGAGE", "HOA", "PROPERTY MGMT", "PROPERTY MANAGEMENT",
                 "APARTMENTS", "REALTY", "LEASING", "GUARANTEED RATE", "ROCKET MORTGAGE",
                 "MR COOPER", "LOANDEPOT", "PENNYMAC", "NEWREZ", "SHELLPOINT",
                 "TASKRABBIT", "ANGI", "THUMBTACK")),
    ("Health", ("PHARMACY", "CVS", "WALGREENS", "RITE AID", "MEDICAL", "DENTAL", "DENTIST",
                "CLINIC", "HOSPITAL", "OPTOMETRY", "OPTICAL", "PHYSICIAN", "THERAPY",
                "URGENT CARE", "KAISER", "LABCORP", "QUEST DIAG", "GYM", "FITNESS", "YOGA",
                "CROSSFIT", "ORTHO", "UPMC", "UPMCHEALTH", "UPMCHEALTHSERVICES",
                "HEALTHCARE", "HEALTH SERVICES",
                "HEALTH SYSTEM", "BLUECHEW", "TELEHEALTH")),
    ("Insurance", ("INSURANCE", "GEICO", "STATE FARM", "PROGRESSIVE", "ALLSTATE", "FARMERS INS",
                   "LIBERTY MUTUAL", "USAA", "LEMONADE", "METLIFE", "AETNA", "ANTHEM",
                   "BLUE CROSS", "BLUE SHIELD", "CIGNA", "UNITEDHEALTH", "TRAVELERS",
                   "NATIONWIDE", "ERIE INS", "AMICA", "THE HARTFORD", "PLYMOUTH ROCK")),
    ("Travel", ("AIRLINE", "AIRLINES", "UNITED", "DELTA", "AMERICAN AIR", "SOUTHWEST", "JETBLUE",
                "ALASKA AIR", "SPIRIT", "FRONTIER", "HOTEL", "MARRIOTT", "HILTON", "HYATT",
                "AIRBNB", "VRBO", "HERTZ", "AVIS", "ENTERPRISE RENT", "BOOKING.COM", "EXPEDIA",
                "KAYAK", "PRICELINE", "RESORT", "INN", "MOTEL", "TSA", "LOUNGE")),
    ("Shopping", ("AMAZON", "AMZN", "TARGET", "WALMART", "BEST BUY", "BESTBUY", "IKEA",
                  "HOME DEPOT", "LOWES", "LOWE'S", "COSTCO", "NORDSTROM", "MACY", "GAP",
                  "OLD NAVY", "H&M", "ZARA", "UNIQLO", "NIKE", "ADIDAS", "REI", "APPLE STORE",
                  "APPLE.COM", "ETSY", "EBAY", "WAYFAIR", "CRATE", "WILLIAMS-SONOMA",
                  "SEPHORA", "ULTA", "TJ MAXX", "TJMAXX", "MARSHALLS", "ROSS", "DOLLAR",
                  "STAPLES", "OFFICE DEPOT", "MICRO CENTER", "SHOP", "VINTED",
                  "POSHMARK", "DEPOP", "MERCARI", "THREDUP", "JCPENNEY", "JC PENNEY",
                  "KOHL", "KOHLS", "DILLARD", "AFFIRM", "KLARNA", "AFTERPAY", "HARDWARE",
                  "ACE HDWE", "ACE HARDWARE", "TRUE VALUE", "MENARDS", "TRACTOR SUPPLY")),
    ("Entertainment", ("CINEMA", "THEATRE", "THEATER", "AMC", "REGAL", "TICKETMASTER",
                       "STUBHUB", "STEAM", "STEAMGAMES", "NINTENDO", "PLAYSTATION", "XBOX",
                       "CONCERT", "MUSEUM", "ZOO", "AQUARIUM", "BOWLING", "GOLF", "SKI",
                       "SPOTIFY", "NETFLIX", "HULU")),
    ("Personal Care", ("SALON", "BARBER", "BARBERS", "HAIR", "SPA", "MASSAGE", "NAILS", "LAUNDRY",
                       "DRY CLEAN", "CLEANERS")),
    ("Education", ("TUITION", "UNIVERSITY", "COLLEGE", "UDEMY", "COURSERA", "SKILLSHARE",
                   "MASTERCLASS", "SCHOOL", "BOOKSTORE", "STUDENT LOAN", "NAVIENT", "NELNET",
                   "SALLIE MAE", "MOHELA")),
    ("Gifts & Donations", ("DONATION", "CHARITY", "GOFUNDME", "RED CROSS", "UNICEF",
                           "FOUNDATION", "CHURCH", "TEMPLE", "MOSQUE", "SYNAGOGUE", "WIKIMEDIA")),
    ("Pets", ("PETCO", "PETSMART", "CHEWY", "VETERINARY", "VET", "ANIMAL HOSPITAL", "PET")),
    ("Kids", ("DAYCARE", "CHILDCARE", "PRESCHOOL", "TOYS", "BABY", "PEDIATRIC",
              "BRIGHTWHEEL", "BRGHTWHL", "KINDERCARE", "BRIGHT HORIZONS", "GODDARD",
              "MONTESSORI", "TUITION EXPRESS", "PRIMROSE SCHOOL")),
    ("Taxes", ("IRS", "TAX PAYMENT", "FRANCHISE TAX", "DEPT OF REVENUE", "TURBOTAX", "H&R BLOCK",
               "PROPERTY TAX", "TAX COLLECTOR")),
    ("Cash & ATM", ("ATM", "CASH WITHDRAWAL", "WITHDRAWAL", "CHECK")),
    ("Investments", ("VANGUARD", "FIDELITY", "SCHWAB", "ROBINHOOD", "BETTERMENT", "WEALTHFRONT",
                     "E*TRADE", "ETRADE", "COINBASE", "ACORNS", "401K", "IRA", "BROKERAGE",
                     "ISHARES", "SPDR", "INVESCO", " ETF", "INDEX FUND", "MUTUAL FUND")),
    ("Business", ("FEDEX", "UPS", "USPS", "SHIPPING", "SQUARESPACE", "GODADDY", "NAMECHEAP",
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

# Words too generic to identify an institution.
_GENERIC_ORG_WORDS = {"BANK", "CARD", "CARDS", "CREDIT", "FINANCIAL", "FINANCE", "INVESTMENTS",
                      "SAVINGS", "FEDERAL", "NATIONAL", "UNION", "TRUST", "GROUP", "SERVICES",
                      "COMPANY", "CORP", "HOLDINGS", "AMERICA", "USA"}


def own_debt_issuers(conn: sqlite3.Connection) -> set[str]:
    """Institutions where the ledger already holds a card or a loan.

    A payment to one of those is money moving between accounts that are both
    on file, even when the two halves never match exactly — partial payments
    and statement timing keep pair_transfers from seeing them as a pair.
    """
    out: set[str] = set()
    for r in conn.execute("""SELECT DISTINCT c.name FROM accounts a
                             JOIN connections c ON c.conn_id = a.conn_id
                             WHERE a.kind IN ('credit', 'loan')"""):
        for word in re.split(r"[^A-Za-z0-9]+", (r["name"] or "").upper()):
            if len(word) >= 4 and word not in _GENERIC_ORG_WORDS:
                out.add(word)
    return out


def own_accounts(conn: sqlite3.Connection) -> dict:
    """Tokens that name one of the user's own accounts.

    Names lose a trailing "(1234)" and any " - 1234" suffix, so
    "Checking - 9538 (9538)" contributes CHECKING and 9538. Names under five
    characters are dropped: "Car" and "Active" are real account names here and
    far too generic to carry a decision on their own.
    """
    names: set[str] = set()
    digits: set[str] = set()
    for r in conn.execute("SELECT name FROM accounts"):
        n = (r["name"] or "").upper()
        for d in re.findall(r"\((\d{3,})\)", n):
            digits.add(d)
        base = re.sub(r"\s*\(\d+\)\s*$", "", n).strip()
        base = re.sub(r"\s*-\s*\d+\s*$", "", base).strip()
        if len(base) >= 5:
            names.add(base)
    return {"names": names, "digits": digits}


def names_own_account(description: str, own: dict | None) -> bool:
    if not own:
        return False
    desc = (description or "").upper()
    return match.any_mention(desc, own["names"]) or any(d in desc for d in own["digits"])


def is_internal_transfer(description: str, own: dict | None) -> bool:
    desc = (description or "").upper()
    if VAULT_SHAPE.search(desc):
        return True
    return bool(TRANSFER_SHAPE.search(desc)) and names_own_account(desc, own)


def _delivery_category(description: str) -> tuple[str | None, str | None]:
    """The shop behind a delivery order, if it can be recognized."""
    desc = (description or "").strip()
    remainder = DELIVERY_PREFIX.sub("", desc, count=1).strip()
    if not remainder or remainder == desc:
        return None, None
    svc = catalog.match_service(remainder)
    if svc and svc.get("category"):
        return svc["category"], f"delivery:{remainder}:service:{svc['id']}"
    for name, keywords in KEYWORDS:
        hit = match.first_mention(remainder, keywords)
        if hit:
            return name, f"delivery:{remainder}:keyword:{hit}"
    # Processors truncate the shop and drop its spaces: THEHOMEDE, GIANTEAGL.
    for name, keywords in KEYWORDS:
        for k in keywords:
            if match.squashed_match(remainder, k):
                return name, f"delivery:{remainder}:truncated:{k}"
    return DELIVERY_DEFAULT, f"delivery:{remainder}:unrecognized"


def heuristic_category(description: str, amount_cents: int, key: str | None = None,
                       account_kind: str | None = None, own_issuers: set[str] | None = None,
                       own: dict | None = None) -> str | None:
    name, _ = heuristic_with_reason(description, amount_cents, key, account_kind, own_issuers, own)
    return name


def heuristic_with_reason(description: str, amount_cents: int, key: str | None = None,
                          account_kind: str | None = None, own_issuers: set[str] | None = None,
                          own: dict | None = None) -> tuple[str | None, str | None]:
    """The category and the reason it was chosen.

    The reason is the whole point of the pair: a category on its own cannot be
    audited, while "Gas because the keyword MOBIL matched" can be scanned by
    eye and the wrong ones picked out in seconds.
    """
    desc = (description or "").upper()
    svc = catalog.match_service(desc)
    # First, because "Overdraft: To Checking - 9538" is money moving while
    # "OVERDRAFT FEE" is a charge, and only the shape tells them apart.
    if is_internal_transfer(desc, own):
        return "Transfer", "transfer:own-account"
    # A bare FEE catches what the list does not — "Robo Management Fee",
    # "Origination Fee" — and COFFEE is safe, since a letter may not precede.
    fee = match.first_mention(desc, FEE_KEYWORDS) or match.first_mention(desc, ("FEE", "FEES"))
    if fee:
        return "Fees & Interest", f"fee:{fee}"
    if account_kind in ("investment", "loan"):
        # Money moving inside a brokerage, a retirement plan or a loan is not
        # household cash flow: buying an ETF is not spending, a 401(k)
        # contribution landing is not income, and a loan's disbursement is
        # neither. Fees charged inside one are real, and were caught above.
        return "Transfer", f"account-kind:{account_kind}"
    moved = match.first_mention(desc, TRANSFER_KEYWORDS)
    if moved:
        return "Transfer", f"transfer:{moved}"
    card = match.first_mention(desc, CARD_PAYMENT_KEYWORDS)
    if card:
        # Paying a card the ledger already holds is a transfer. Paying one it
        # does not is the only trace of that spending, so it stays an expense.
        issuer = match.first_mention(desc, own_issuers) if own_issuers else None
        if issuer:
            return "Transfer", f"card-payment:{card}:own-issuer:{issuer}"
        return "Card Payments", f"card-payment:{card}"
    earned = match.first_mention(desc, INCOME_KEYWORDS) if amount_cents > 0 else None
    if earned:
        return "Income", f"income:{earned}"
    delivered, why = _delivery_category(desc)
    if delivered:
        return delivered, why
    if svc and svc.get("category"):
        return svc["category"], f"service:{svc['id']}"
    for name, keywords in KEYWORDS:
        hit = match.first_mention(desc, keywords)
        if hit:
            return name, f"keyword:{hit}"
    credited = match.first_mention(desc, ("INTEREST", "CREDIT")) if amount_cents > 0 else None
    if credited:
        return "Income", f"income:{credited}"
    return None, None


def decide(conn: sqlite3.Connection, rules: list[dict], description: str, key: str,
           amount_cents: int, account_kind: str | None = None,
           own_issuers: set[str] | None = None,
           own: dict | None = None) -> tuple[int | None, str | None, dict | None, str | None]:
    """(category_id, source, matching_rule, reason) for one transaction."""
    for rule in rules:
        if rule_matches(rule, description, key):
            # Stamped by the rule, not by its author. A row a rule decided has
            # to stay re-derivable: stamping it 'user' made it indistinguishable
            # from a category set by hand and froze it against every later fix,
            # which is exactly backwards when the rule itself is the mistake.
            return rule["category_id"], "rule", rule, f"rule:{rule['id']}"
    if own_issuers is None:
        own_issuers = own_debt_issuers(conn)
    if own is None:
        own = own_accounts(conn)
    name, why = heuristic_with_reason(description, amount_cents, key, account_kind, own_issuers, own)
    if name:
        return category_id(conn, name), "heuristic", None, why
    return None, None, None, None


def categorize(conn: sqlite3.Connection, *, only_uncategorized: bool = True,
               include_user: bool = False, ids: list[str] | None = None) -> int:
    """Run rules and heuristics. Returns how many rows changed."""
    rules = load_rules(conn)
    issuers = own_debt_issuers(conn)
    own = own_accounts(conn)
    where = ["t.removed_at IS NULL"]
    params: list = []
    if ids:
        where.append("t.id IN (%s)" % ",".join("?" * len(ids)))
        params.extend(ids)
    elif only_uncategorized:
        where.append("t.category_id IS NULL")
    if not include_user:
        where.append("(t.category_source IS NULL OR t.category_source NOT IN ('user','claude'))")
    changed = 0
    # The account's kind decides whether its rows can be spending at all, so
    # it is joined in rather than looked up per row.
    sql = ("SELECT t.id, t.description, t.payee_key, t.amount_cents, t.category_id, t.category_reason, t.category_source, a.kind AS account_kind "
           "FROM transactions t LEFT JOIN accounts a ON a.id = t.account_id WHERE ")
    for row in db.rows(conn, sql + " AND ".join(where), params):
        key = row["payee_key"] or payee_key(row["description"])
        cid, source, rule, why = decide(conn, rules, row["description"], key, row["amount_cents"],
                                        row["account_kind"], issuers, own)
        if cid is None:
            # Nothing stands behind this category any more. On a re-derivation
            # that means the keyword that produced it has been corrected, and
            # leaving the old answer in place would keep a known-wrong category
            # forever; uncategorized is worse to look at and better to trust.
            if not only_uncategorized and row["category_id"] is not None \
                    and row["category_source"] == "heuristic":
                conn.execute(
                    """UPDATE transactions SET category_id = NULL, category_source = NULL,
                         category_reason = NULL, category_rule_id = NULL WHERE id = ?""",
                    (row["id"],))
                changed += 1
            continue
        same = cid == row["category_id"]
        if same and why == row["category_reason"]:
            continue
        conn.execute(
            """UPDATE transactions SET category_id = ?, category_source = ?, category_reason = ?,
                 category_rule_id = ? WHERE id = ?""",
            (cid, source, why, rule["id"] if rule else None, row["id"]))
        if rule:
            conn.execute("UPDATE rules SET hits = hits + 1 WHERE id = ?", (rule["id"],))
        # A row whose category was already right but whose reason was not
        # recorded is not a change worth reporting; the reason is bookkeeping.
        if not same:
            changed += 1
    changed += pair_transfers(conn)
    conn.commit()
    return changed


def reconcile_sources(conn: sqlite3.Connection, *, apply: bool = False) -> list[dict]:
    """Restamp rows that a rule decided but that are recorded as hand-set.

    Rule output used to carry the rule author's source, so rows a rule got
    wrong are sitting in the database indistinguishable from categories the
    user chose, and frozen against repair. A row is only restamped when a rule
    still matches it *and* its current category is what that rule produces;
    anything else is left alone, because it might really have been hand-set.
    """
    rules = load_rules(conn)
    moved = []
    for row in db.rows(conn, """
            SELECT t.id, t.description, t.payee_key, t.category_id, t.category_source, c.name AS category
            FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.removed_at IS NULL AND t.category_source IN ('user', 'claude')"""):
        key = row["payee_key"] or payee_key(row["description"])
        for rule in rules:
            if rule_matches(rule, row["description"], key) and rule["category_id"] == row["category_id"]:
                moved.append({"id": row["id"], "description": row["description"],
                              "category": row["category"], "was": row["category_source"],
                              "rule_id": rule["id"]})
                if apply:
                    conn.execute(
                        """UPDATE transactions SET category_source = 'rule', category_reason = ?,
                             category_rule_id = ? WHERE id = ?""",
                        (f"rule:{rule['id']}", rule["id"], row["id"]))
                break
    if apply:
        conn.commit()
    return moved


def preview(conn: sqlite3.Connection, *, include_user: bool = False) -> list[dict]:
    """What a re-derivation would change, without changing it."""
    rules = load_rules(conn)
    issuers = own_debt_issuers(conn)
    own = own_accounts(conn)
    where = ["t.removed_at IS NULL"]
    if not include_user:
        where.append("(t.category_source IS NULL OR t.category_source NOT IN ('user','claude'))")
    out = []
    for row in db.rows(conn, """
            SELECT t.id, t.posted_date, t.description, t.payee_key, t.amount_cents, t.category_id,
                   a.kind AS account_kind, c.name AS current
            FROM transactions t LEFT JOIN accounts a ON a.id = t.account_id
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE """ + " AND ".join(where)):
        key = row["payee_key"] or payee_key(row["description"])
        cid, _source, _rule, why = decide(conn, rules, row["description"], key, row["amount_cents"],
                                          row["account_kind"], issuers, own)
        if cid == row["category_id"]:
            continue
        out.append({"id": row["id"], "date": row["posted_date"], "description": row["description"],
                    "amount_cents": row["amount_cents"], "from": row["current"],
                    "to": category_name(conn, cid), "reason": why})
    return out


def set_category(conn: sqlite3.Connection, tx_ids: list[str], category: str, source: str = "user") -> int:
    cid = category_id(conn, category, create=True)
    n = 0
    for tid in tx_ids:
        cur = conn.execute(
            """UPDATE transactions SET category_id = ?, category_source = ?, category_reason = ?,
                 category_rule_id = NULL WHERE id = ?""",
            (cid, source, f"set-by:{source}", tid))
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
                    conn.execute(
                        """UPDATE transactions SET category_id = ?, category_source = 'heuristic',
                             category_reason = 'transfer:paired' WHERE id = ?""",
                        (transfer, tid))
                    used.add(tid)
                changed += 2
                break
    return changed
