"""Descriptor-level tests for the classifier.

Every case here is a real descriptor from a real bank feed. A bank descriptor
is cramped and abbreviated, so the classifier's failures are not "no answer" —
they are confident wrong answers that look identical to right ones in every
report. These pin the ones that were found by reading the results.
"""
from ledger import categorize, match


def cat(description, amount=-50, account_kind=None, issuers=None, own=None):
    return categorize.heuristic_category(description, amount, None, account_kind, issuers, own)


def test_a_keyword_must_land_on_a_token_boundary():
    # MOBIL inside GOMOBILEPGH (Pittsburgh parking) filed 8 rows under Gas, and
    # SPIRIT inside WINE AND SPIRITS filed a liquor store under airlines.
    assert cat("GOMOBILEPGH") != "Gas"
    assert cat("SIMPLEMOBILE SERVICES") != "Gas"
    assert cat("WINE AND SPIRITS 0260") == "Dining"
    assert cat("WINE & SPIRITS 0260") == "Dining"
    # The genuine matches still land.
    assert cat("MOBIL OIL 1234") == "Gas"
    assert cat("SPIRIT AIRLINES") == "Travel"


def test_punctuated_and_prefix_keywords_survive_the_boundary_rule():
    assert cat("PG&E ELECTRIC PAYMENT") == "Utilities"
    assert cat("H-E-B #443") == "Groceries"
    assert cat("O'REILLY AUTO PARTS") == "Transportation"
    assert cat("BP#9622291OMANSH ENTPRIS") == "Gas"
    assert cat("PHO VIETNAM") == "Dining"
    assert cat("VET CLINIC OF SHADYSIDE") in ("Pets", "Health")


def test_the_matcher_refuses_fragments():
    assert match.mentions("WINE AND SPIRITS", "SPIRITS")
    assert not match.mentions("WINE AND SPIRITS", "SPIRIT")
    assert not match.mentions("GOMOBILEPGH", "MOBIL")
    assert match.mentions("PG&E PAYMENT", "PG&E")
    assert match.mentions("BP#9622291OMANSH", "BP#")


def test_squashed_match_is_for_truncated_merchant_names():
    assert match.squashed_match("BESTBUY", "BEST BUY")
    assert match.squashed_match("GIANTEAGL", "GIANT EAGLE")
    assert match.squashed_match("THEHOMEDE", "THE HOME DEPOT")
    # Too short to mean anything.
    assert not match.squashed_match("CVS", "CVS PHARMACY")
    assert not match.squashed_match("ALDI", "ALDI")


def test_a_store_number_after_a_merchant_does_not_break_the_match():
    # Banks jam a store or transaction number straight onto the name.
    assert match.mentions("FEDEX259723989", "FEDEX")
    assert match.mentions("WENDYS 8222", "WENDYS")
    assert match.mentions("BP#9622291OMANSH", "BP")
    # A number in front is a different story: 76 inside 1976 is not the brand.
    assert not match.mentions("ROUTE 1976 DINER", "76")
    assert not match.mentions("GOMOBILEPGH", "MOBIL")


class _Own:
    """The account index heuristic_category expects."""
    def __new__(cls, names, digits=()):
        return {"names": set(names), "digits": set(digits)}


OWN = _Own({"CHECKING", "SAVINGS", "EMERGENCY FUND", "GOLD FUND"}, {"9538", "8966"})


def test_money_moving_between_your_own_accounts_is_never_spending():
    # This was $6,208 of internal movement filed under Cash & ATM, and the
    # matching half filed as income.
    assert cat("Withdrawal: To Checking - 9538", own=OWN) == "Transfer"
    assert cat("Withdrawal: To savings balance", own=OWN) == "Transfer"
    assert cat("Deposit: From checking balance", 120000, own=OWN) == "Transfer"
    assert cat("From checking balance", 50000, own=OWN) == "Transfer"
    assert cat("Deposit: From Gold Fund Vault", 10000, own=OWN) == "Transfer"
    assert cat("To Car Vault", own=OWN) == "Transfer"
    # An overdraft that moves money is a transfer; an overdraft charge is a fee.
    assert cat("Overdraft: To Checking - 9538", own=OWN) == "Transfer"
    assert cat("OVERDRAFT FEE", own=OWN) == "Fees & Interest"


def test_the_transfer_shape_alone_is_not_enough():
    # A merchant descriptor must never be swallowed by the transfer rule.
    assert cat("TASKRABBIT* DEPOSIT", own=OWN) != "Transfer"
    assert cat("ATM: EFT", own=OWN) == "Cash & ATM"
    # Naming an account you do not hold proves nothing.
    assert cat("Withdrawal: To Checking - 1111", own=_Own({"EMERGENCY FUND"})) != "Transfer"


def test_a_charge_inside_a_brokerage_is_still_a_charge():
    # The blanket investment rule was swallowing real fees.
    assert cat("Robo Management Fee 2026-07-01 to 2026-08-01", account_kind="investment") == "Fees & Interest"
    assert cat("Origination Fee", account_kind="loan") == "Fees & Interest"
    assert cat("Invesco S&P 500 Equal Weight ETF", account_kind="investment") == "Transfer"
    # COFFEE must not read as a fee.
    assert cat("SQ *DELANIE'S COFFEE SOUT") == "Dining"


def test_a_delivery_platform_is_a_channel_not_a_merchant():
    assert cat("DD *DOORDASH THEHOMEDE") == "Shopping"
    assert cat("DD *DOORDASH BESTBUY") == "Shopping"
    assert cat("DD *DOORDASHKOHLS") == "Shopping"
    assert cat("DD *DOORDASHCVS") == "Health"
    # The ones that were already right must stay right.
    assert cat("DD *DOORDASH ALDI") == "Groceries"
    assert cat("DD *DOORDASH GIANTEAGL") == "Groceries"
    assert cat("DD *DOORDASH DUNKIN") == "Dining"
    # An unrecognizable shop falls back to the platform's usual business.
    assert cat("DD *DOORDASH TASTEOFIN") == "Dining"
    assert cat("DOORDASH*08/18-3 ORDER") == "Dining"


def test_squashed_matching_only_runs_one_way():
    # TSAOCAA is a bubble tea shop. A three-letter airport keyword must not
    # claim it just because the name starts with those letters.
    assert not match.squashed_match("TSAOCAA", "TSA")
    assert cat("DD *DOORDASH TSAOCAA") == "Dining"
    assert match.squashed_match("GIANTEAGL", "GIANT EAGLE")
