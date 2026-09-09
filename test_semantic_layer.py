import json
import os
import tempfile

import pytest

import semantic_layer


@pytest.fixture
def temp_terms_file(monkeypatch):
    """
    Points semantic_layer at a temporary, empty JSON file for the
    duration of one test, so tests never read/write the real
    semantic_terms.json. Cleans up automatically afterward.
    """
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump({}, f)

    # monkeypatch temporarily overrides the module-level constant,
    # automatically restored after the test — no manual cleanup needed
    monkeypatch.setattr(semantic_layer, "SEMANTIC_TERMS_PATH", path)

    yield path

    os.remove(path)


def test_add_and_find_single_term(temp_terms_file):
    semantic_layer.add_new_term("concert_singer", "high performer", "Age < 30")
    result = semantic_layer.find_relevant_terms("Who are the high performer singers?", "concert_singer")
    assert result == {"high performer": "Age < 30"}


def test_find_returns_empty_when_no_match(temp_terms_file):
    semantic_layer.add_new_term("concert_singer", "high performer", "Age < 30")
    result = semantic_layer.find_relevant_terms("What is the average age?", "concert_singer")
    assert result == {}


def test_find_returns_empty_for_unknown_db(temp_terms_file):
    semantic_layer.add_new_term("concert_singer", "high performer", "Age < 30")
    result = semantic_layer.find_relevant_terms("high performer question", "some_other_db")
    assert result == {}


def test_multiple_terms_in_one_question(temp_terms_file):
    semantic_layer.add_new_term("concert_singer", "high performer", "Age < 30")
    semantic_layer.add_new_term("concert_singer", "veteran performer", "Age > 50")

    result = semantic_layer.find_relevant_terms(
        "Compare high performer and veteran performer singers", "concert_singer"
    )
    assert result == {"high performer": "Age < 30", "veteran performer": "Age > 50"}


def test_inject_semantic_context_formats_correctly(temp_terms_file):
    semantic_layer.add_new_term("concert_singer", "high performer", "Age < 30")
    context = semantic_layer.inject_semantic_terms("Who are the high performer singers?", "concert_singer")
    assert 'high performer' in context
    assert 'Age < 30' in context


def test_inject_semantic_context_empty_when_no_match(temp_terms_file):
    semantic_layer.add_new_term("concert_singer", "high performer", "Age < 30")
    context = semantic_layer.inject_semantic_terms("What is the average age?", "concert_singer")
    assert context == ""


def test_remove_term(temp_terms_file):
    semantic_layer.add_new_term("concert_singer", "high performer", "Age < 30")
    semantic_layer.remove_terms("concert_singer", "high performer")
    result = semantic_layer.find_relevant_terms("high performer question", "concert_singer")
    assert result == {}


def test_list_terms(temp_terms_file):
    semantic_layer.add_new_term("concert_singer", "high performer", "Age < 30")
    semantic_layer.add_new_term("concert_singer", "veteran performer", "Age > 50")
    terms = semantic_layer.list_terms("concert_singer")
    assert terms == {"high performer": "Age < 30", "veteran performer": "Age > 50"}