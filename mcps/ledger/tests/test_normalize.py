from conftest import load_fixture
import pytest

from ledger import catalog
from ledger.normalize import clean, payee_key

TABLE = load_fixture("payee_table.json")


@pytest.mark.parametrize("description,expected", TABLE, ids=[t[0][:30] or "empty" for t in TABLE])
def test_payee_key_table(description, expected):
    assert payee_key(description) == expected


def test_same_merchant_different_store_numbers_group_together():
    assert payee_key("SQ *BLUE BOTTLE 0421 SAN FRANCISCO CA") == payee_key("SQ *BLUE BOTTLE 0488 OAKLAND CA")


def test_clean_keeps_at_most_three_tokens():
    assert clean("ONE TWO THREE FOUR FIVE") == "ONE TWO THREE"


def test_catalog_longest_alias_wins():
    assert catalog.match_service("AMAZON PRIME*1A2B AMZN.COM/BILL")["id"] == "amazon-prime"
    assert catalog.match_service("GOOGLE *YouTube Premium")["id"] == "youtube-premium"
    assert catalog.match_service("SAFEWAY #1234") is None


def test_catalog_matches_whole_words_only():
    assert catalog.match_service("MAXWELL HOUSE COFFEE") is None   # not "Max"
    assert catalog.match_service("HBO MAX 12.99")["id"] == "max"
