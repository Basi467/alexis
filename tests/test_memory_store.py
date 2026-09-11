"""Covers memory/store.py -- the actual persistent-memory system (save_memory/
recall_memory, update_project/recall_project, save_behavior_rule) -- previously
the one pure-logic module with zero test coverage despite being central and
behind a real "Alexis forgot my stored music preference" bug found in live use.

Operates on the real, shared SQLite/FAISS-backed database (there's no
dependency-injection seam for a test database without a larger refactor), so
every test uses obviously-fake, uniquely-prefixed text and cleans its own rows
up afterward via a fixture -- never touches or leaves behind anything
resembling the user's real facts/projects/rules.

ask_groq (used by remember()/save_rule() to decide update-vs-new whenever
there are candidates -- which for save_rule means ALL existing rules, real
ones included, every single call) is replaced with a targeted fake that only
ever claims "this updates candidate N" when our own test marker is actually
one of the candidates offered, falling back to NEW otherwise. That keeps
these tests from ever being able to overwrite a real fact/rule just because
it happened to look similar, and means no real API calls happen here either.
"""
import re
import uuid

import pytest

import config
config.configure_logging()

from memory import store


def _targeted_ask_groq(target_marker):
    """Scans the numbered candidate list embedded in the real prompt and
    returns the number of the line containing target_marker, or NEW if it
    isn't among the candidates offered."""
    def fake(prompt, model=None, **kwargs):
        for line in prompt.splitlines():
            m = re.match(r"(\d+)\.\s", line)
            if m and target_marker in line:
                return m.group(1), None
        return "NEW", None
    return fake


@pytest.fixture
def fact_marker():
    return f"ZzzTestMemory{uuid.uuid4().hex[:8]}"


@pytest.fixture
def project_marker():
    return f"ZzzTestProject{uuid.uuid4().hex[:8]}"


@pytest.fixture
def rule_marker():
    return f"ZzzTestRule{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _cleanup_test_rows():
    """Deletes any row whose text/name starts with a test prefix after every
    test, regardless of pass/fail, then rebuilds the in-memory FAISS indexes
    so they match -- a broken test can't leave junk in the real database or a
    stale vector behind in the index."""
    yield
    store._conn.execute("DELETE FROM facts WHERE text LIKE 'ZzzTestMemory%'")
    store._conn.execute("DELETE FROM projects WHERE name LIKE 'ZzzTestProject%'")
    store._conn.execute("DELETE FROM rules WHERE text LIKE 'ZzzTestRule%'")
    store._conn.commit()
    store._load_indexes()


# --- facts: save_memory / recall_memory ---

def test_remember_and_recall_roundtrip(fact_marker, monkeypatch):
    monkeypatch.setattr(store, "ask_groq", _targeted_ask_groq(fact_marker))
    fact = f"{fact_marker}: user's favorite color is teal."
    store.remember(fact)

    results = store.recall(f"{fact_marker} favorite color")
    assert fact in results


def test_recall_unrelated_query_does_not_return_it(fact_marker, monkeypatch):
    monkeypatch.setattr(store, "ask_groq", _targeted_ask_groq(fact_marker))
    fact = f"{fact_marker}: user's favorite color is teal."
    store.remember(fact)

    results = store.recall("completely unrelated query about deep sea navigation")
    assert fact not in results


def test_remember_creates_separate_entries_for_unrelated_facts(fact_marker, monkeypatch):
    monkeypatch.setattr(store, "ask_groq", _targeted_ask_groq(fact_marker))
    fact1 = f"{fact_marker} A: user likes tea."
    fact2 = f"{fact_marker} B: user's favorite programming language is Python."
    store.remember(fact1)
    store.remember(fact2)

    rows = store._conn.execute(
        "SELECT text FROM facts WHERE text LIKE ?", (f"{fact_marker}%",)
    ).fetchall()
    assert {row["text"] for row in rows} == {fact1, fact2}


def test_remember_updates_in_place_instead_of_duplicating(fact_marker, monkeypatch):
    monkeypatch.setattr(store, "ask_groq", _targeted_ask_groq(fact_marker))
    original = f"{fact_marker}: user's favorite color is teal."
    store.remember(original)

    updated = f"{fact_marker}: user's favorite color is actually crimson now."
    store.remember(updated)

    rows = store._conn.execute(
        "SELECT text FROM facts WHERE text LIKE ?", (f"{fact_marker}%",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["text"] == updated


# --- projects: update_project / recall_project ---

def test_update_project_creates_new(project_marker):
    store.update_project(project_marker, "Just started.")

    result = store.recall_project(project_marker)
    assert result is not None
    assert result["name"] == project_marker
    assert result["status"] == "Just started."


def test_update_project_exact_match_updates_in_place(project_marker):
    store.update_project(project_marker, "Just started.")
    store.update_project(project_marker, "Nearly done.")

    rows = store._conn.execute(
        "SELECT * FROM projects WHERE name = ?", (project_marker,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "Nearly done."


def test_update_project_substring_match_updates_same_row(project_marker):
    full_name = f"{project_marker} voice assistant"
    store.update_project(full_name, "Just started.")
    store.update_project(project_marker, "Nearly done.")  # shorter name, substring of the above

    rows = store._conn.execute(
        "SELECT * FROM projects WHERE name LIKE ?", (f"{project_marker}%",)
    ).fetchall()
    assert len(rows) == 1, "should update the same row, not create a second one"
    assert rows[0]["status"] == "Nearly done."


def test_recall_project_returns_none_for_unknown_project(project_marker):
    assert store.recall_project(project_marker) is None


# --- rules: save_behavior_rule / get_all_rules ---

def test_save_rule_creates_new_and_is_listed(rule_marker, monkeypatch):
    monkeypatch.setattr(store, "ask_groq", _targeted_ask_groq(rule_marker))
    rule = f"{rule_marker}: always address the user as boss."
    store.save_rule(rule)

    assert rule in store.get_all_rules()


def test_save_rule_updates_existing_rule_in_place(rule_marker, monkeypatch):
    monkeypatch.setattr(store, "ask_groq", _targeted_ask_groq(rule_marker))
    original = f"{rule_marker}: always address the user as boss."
    store.save_rule(original)

    revised = f"{rule_marker}: actually, address the user as sir instead."
    store.save_rule(revised)

    matching = [r for r in store.get_all_rules() if r.startswith(rule_marker)]
    assert matching == [revised]
