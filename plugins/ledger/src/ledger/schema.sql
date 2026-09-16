-- ledger schema. Money is integer cents; times are epoch seconds; posted_date
-- is the local calendar day used for every grouping.

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS connections (
  conn_id    TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  org_id     TEXT,
  org_url    TEXT,
  sfin_url   TEXT,
  first_seen INTEGER NOT NULL,
  last_seen  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
  id              TEXT PRIMARY KEY,
  conn_id         TEXT,
  name            TEXT NOT NULL,
  currency        TEXT NOT NULL DEFAULT 'USD',
  balance_cents   INTEGER NOT NULL DEFAULT 0,
  available_cents INTEGER,
  balance_date    INTEGER,
  -- checking|savings|credit|loan|investment|other|unknown
  kind            TEXT NOT NULL DEFAULT 'unknown',
  kind_source     TEXT NOT NULL DEFAULT 'heuristic',
  hidden          INTEGER NOT NULL DEFAULT 0,
  first_seen      INTEGER NOT NULL,
  last_seen       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
  id              TEXT PRIMARY KEY,
  account_id      TEXT NOT NULL,
  posted          INTEGER NOT NULL,
  posted_date     TEXT NOT NULL,
  transacted_at   INTEGER,
  amount_cents    INTEGER NOT NULL,
  currency        TEXT NOT NULL DEFAULT 'USD',
  description     TEXT NOT NULL DEFAULT '',
  payee_key       TEXT NOT NULL DEFAULT '',
  pending         INTEGER NOT NULL DEFAULT 0,
  extra_json      TEXT,
  source          TEXT NOT NULL DEFAULT 'simplefin',
  category_id     INTEGER,
  -- rule|user|claude|import|heuristic
  category_source TEXT,
  ignored         INTEGER NOT NULL DEFAULT 0,
  superseded_by   TEXT,
  removed_at      INTEGER,
  first_seen      INTEGER NOT NULL,
  last_seen       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tx_account_posted ON transactions(account_id, posted);
CREATE INDEX IF NOT EXISTS ix_tx_payee ON transactions(payee_key);
CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions(posted_date);
CREATE INDEX IF NOT EXISTS ix_tx_category ON transactions(category_id);

CREATE TABLE IF NOT EXISTS balance_snapshots (
  account_id      TEXT NOT NULL,
  day             TEXT NOT NULL,
  balance_cents   INTEGER NOT NULL,
  available_cents INTEGER,
  PRIMARY KEY (account_id, day)
);

CREATE TABLE IF NOT EXISTS categories (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL UNIQUE,
  parent_id    INTEGER,
  -- expense|income|transfer|fee
  kind         TEXT NOT NULL DEFAULT 'expense',
  aliases_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS rules (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  -- payee|contains|regex
  match_type  TEXT NOT NULL,
  pattern     TEXT NOT NULL,
  category_id INTEGER NOT NULL,
  -- user|claude|import|heuristic
  source      TEXT NOT NULL DEFAULT 'user',
  priority    INTEGER NOT NULL DEFAULT 0,
  created_at  INTEGER NOT NULL,
  hits        INTEGER NOT NULL DEFAULT 0
);

-- Recurring charges. Detected columns are rewritten on every re-detection;
-- user_* columns are the user's overrides and survive it.
CREATE TABLE IF NOT EXISTS series (
  id                   TEXT PRIMARY KEY,
  payee_key            TEXT NOT NULL,
  account_id           TEXT NOT NULL,
  cadence              TEXT NOT NULL,
  interval_days        INTEGER NOT NULL,
  typical_amount_cents INTEGER NOT NULL,
  last_amount_cents    INTEGER NOT NULL,
  first_seen           INTEGER NOT NULL,
  last_seen            INTEGER NOT NULL,
  next_expected        INTEGER,
  occurrences          INTEGER NOT NULL,
  confidence           REAL NOT NULL,
  -- active|lapsed
  status               TEXT NOT NULL DEFAULT 'active',
  is_subscription      INTEGER NOT NULL DEFAULT 0,
  service_id           TEXT,
  user_label           TEXT,
  -- ignored, or NULL
  user_status          TEXT,
  user_is_subscription INTEGER,
  updated_at           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS series_members (
  series_id      TEXT NOT NULL,
  transaction_id TEXT NOT NULL,
  PRIMARY KEY (series_id, transaction_id)
);

CREATE TABLE IF NOT EXISTS goals (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL,
  target_cents INTEGER NOT NULL,
  target_date  TEXT,
  account_id   TEXT,
  category_id  INTEGER,
  start_cents  INTEGER NOT NULL DEFAULT 0,
  created_at   INTEGER NOT NULL,
  notes        TEXT
);

CREATE TABLE IF NOT EXISTS sync_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at   INTEGER NOT NULL,
  finished_at  INTEGER,
  -- claim|backfill|incremental|balances
  kind         TEXT NOT NULL,
  start_date   INTEGER,
  end_date     INTEGER,
  requests     INTEGER NOT NULL DEFAULT 0,
  accounts_n   INTEGER NOT NULL DEFAULT 0,
  tx_new       INTEGER NOT NULL DEFAULT 0,
  tx_updated   INTEGER NOT NULL DEFAULT 0,
  tx_pending   INTEGER NOT NULL DEFAULT 0,
  errlist_json TEXT NOT NULL DEFAULT '[]',
  ok           INTEGER NOT NULL DEFAULT 1,
  error        TEXT
);

CREATE TABLE IF NOT EXISTS insight_dismissals (
  key          TEXT PRIMARY KEY,
  dismissed_at INTEGER NOT NULL,
  by           TEXT
);
