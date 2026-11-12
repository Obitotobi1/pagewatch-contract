"""Local tests for PageWatch (no GenLayer node needed).

They run the contract's real logic against a small stand-in for the genlayer
library. The web fetch is a dictionary of pages, so the tests check the rules
around it: who can confirm or retire, that anyone can re-check, how edits and
layout changes are told apart, which links are refused, and the limits.

Run:  python3 tests/test_pagewatch.py      (or: pytest tests)
"""
import importlib.util
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT = os.path.join(HERE, "..", "pagewatch.py")

ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
URL = "https://example.com/terms"
PHRASE = "We never sell your personal data"
PAGE = "Privacy. We never sell your personal data. Contact us."


class _Addr:
    def __init__(self, h):
        self.as_hex = h


class _Message:
    sender_address = _Addr(ALICE)


class _Web:
    pages = {}

    @classmethod
    def render(cls, url, mode="text"):
        if url not in cls.pages:
            raise Exception("fetch failed")
        return cls.pages[url]


class _Nondet:
    web = _Web


class _Eq:
    @staticmethod
    def strict_eq(fn):
        return fn()


class _Public:
    write = staticmethod(lambda f: f)
    view = staticmethod(lambda f: f)


class _Contract:
    pass


class _TreeMap(dict):
    def __class_getitem__(cls, item):
        return dict


gl = types.SimpleNamespace(Contract=_Contract, message=_Message, nondet=_Nondet,
                           eq_principle=_Eq, public=_Public)
stub = types.ModuleType("genlayer")
stub.gl, stub.TreeMap, stub.u256 = gl, _TreeMap, int
stub.__all__ = ["gl", "TreeMap", "u256"]
sys.modules["genlayer"] = stub

spec = importlib.util.spec_from_file_location("pagewatch", CONTRACT)
pw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pw)


def as_sender(address):
    _Message.sender_address = _Addr(address)


def new_contract():
    c = pw.PageWatch.__new__(pw.PageWatch)
    c.watches, c.by_owner, c.next_id = {}, {}, 1
    _Web.pages = {URL: PAGE}
    as_sender(ALICE)
    return c


def rec(c, i=1):
    return json.loads(c.get_watch(i))


def raises(fn, *args):
    try:
        fn(*args)
    except Exception as e:
        return str(e)
    return None


def active(c):
    c.register(URL, PHRASE)
    c.confirm_baseline(1)


# ---------- registering ----------
def test_bad_links_and_phrases_are_refused():
    c = new_contract()
    for u in ["http://example.com/a", "https://localhost/a", "https://127.0.0.1/a",
              "https://10.0.0.5/a", "https://192.168.1.1/a", "https://169.254.169.254/x",
              "https://user:pw@example.com/a", "https://[::1]/a", "https://intranet/a",
              "https://printer.local/a", "https://example.com/" + "a" * 400]:
        assert raises(c.register, u, PHRASE), u
    assert raises(c.register, URL, "short")
    assert raises(c.register, URL, "x" * 201)
    assert raises(c.register, URL, "          ")


def test_duplicates_and_cap():
    c = new_contract()
    c.register(URL, PHRASE)
    assert "already watch" in raises(c.register, URL, "  " + PHRASE.upper() + " ")
    c.retire(1)
    c.register(URL, PHRASE)                              # allowed again once retired
    c2 = new_contract()
    for i in range(pw.MAX_WATCHES_PER_OWNER):
        c2.register(URL, "a long enough phrase %d" % i)
    assert "limit" in raises(c2.register, URL, "one phrase too many")


# ---------- baseline ----------
def test_baseline_needs_the_phrase_on_the_page_today():
    c = new_contract()
    c.register(URL, "A sentence that is not on the page")
    c.confirm_baseline(1)
    assert rec(c)["status"] == "PENDING" and rec(c)["last_result"] == "NOT_PRESENT"
    assert "re-check" in raises(c.recheck, 1)            # cannot re-check before a baseline
    c2 = new_contract()
    active(c2)
    assert rec(c2)["status"] == "INTACT" and c2.is_intact(1) is True


def test_only_owner_confirms_and_only_once():
    c = new_contract()
    c.register(URL, PHRASE)
    as_sender(BOB)
    assert "owner" in raises(c.confirm_baseline, 1)
    as_sender(ALICE)
    c.confirm_baseline(1)
    assert "already confirmed" in raises(c.confirm_baseline, 1)


def test_unreachable_baseline_is_an_attempt_not_a_crash():
    c = new_contract()
    _Web.pages = {}
    c.register(URL, PHRASE)
    c.confirm_baseline(1)
    assert rec(c)["status"] == "PENDING" and rec(c)["last_result"] == "UNREACHABLE"


# ---------- re-checking ----------
def test_anyone_can_recheck_and_status_follows_the_page():
    c = new_contract()
    active(c)
    as_sender(BOB)                                        # a stranger audits the page
    _Web.pages[URL] = "Privacy. We may sell your personal data to partners."
    c.recheck(1)
    assert rec(c)["status"] == "CHANGED" and c.is_intact(1) is False
    _Web.pages[URL] = PAGE                               # restored
    c.recheck(1)
    assert rec(c)["status"] == "INTACT"
    assert [h["result"] for h in rec(c)["history"]] == ["INTACT", "CHANGED", "INTACT"]


def test_layout_and_case_changes_do_not_count_as_edits():
    c = new_contract()
    active(c)
    _Web.pages[URL] = "PRIVACY\n\n   we  NEVER sell\tyour personal   data \n more text"
    c.recheck(1)
    assert rec(c)["status"] == "INTACT"


def test_unreachable_recheck_keeps_status_and_history():
    c = new_contract()
    active(c)
    _Web.pages = {}
    c.recheck(1)
    r = rec(c)
    assert r["status"] == "INTACT" and r["last_result"] == "UNREACHABLE" and len(r["history"]) == 1


def test_check_cap_and_history_cap():
    c = new_contract()
    active(c)
    for _ in range(pw.MAX_CHECKS - 1):
        c.recheck(1)
    assert len(rec(c)["history"]) == pw.MAX_HISTORY
    assert "limit" in raises(c.recheck, 1)


# ---------- retiring ----------
def test_retire_is_owner_only_and_stops_rechecks():
    c = new_contract()
    active(c)
    as_sender(BOB)
    assert "owner" in raises(c.retire, 1)
    as_sender(ALICE)
    c.retire(1)
    assert "RETIRED" in raises(c.recheck, 1)
    assert "already retired" in raises(c.retire, 1)
    assert c.is_intact(1) is False


# ---------- read API ----------
def test_feed_and_owner_listing():
    c = new_contract()
    c.register(URL, "first watched phrase")
    as_sender(BOB)
    c.register(URL, "second watched phrase")
    c.register(URL, "third watched phrase")
    feed = json.loads(c.get_recent(2))
    assert [w["phrase"] for w in feed] == ["third watched phrase", "second watched phrase"]
    assert len(json.loads(c.get_recent(999))) == 3
    assert [w["id"] for w in json.loads(c.get_watches_by_owner(BOB.upper()))] == [2, 3]
    assert "not found" in raises(c.get_watch, 99)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAIL", name, "->", repr(e))
    print("\n%d passed, %d failed" % (len(tests) - failed, failed))
    sys.exit(1 if failed else 0)
