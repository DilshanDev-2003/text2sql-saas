import os
import sqlite3
import tempfile
import time

import pytest

from db_runner import execute_queries, compare_execution


@pytest.fixture
def db_path():
    """
    Creates a small throwaway SQLite database for the duration of one test,
    then deletes it. Using a fixture means every test gets a fresh, known
    database state, with no leftover data from a previous test run.
    """
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE singer (Singer_ID INTEGER, Name TEXT, Country TEXT, Age INTEGER)")
    conn.executemany(
        "INSERT INTO singer VALUES (?, ?, ?, ?)",
        [
            (1, "Alice", "France", 25),
            (2, "Bob", "France", 43),
            (3, "Carla", "USA", 30),
        ],
    )
    conn.commit()
    conn.close()

    yield path

    os.remove(path)


def test_execute_valid_query_returns_rows(db_path):
    result = execute_queries(db_path, "SELECT Name FROM singer WHERE Country = 'France'")
    assert result == [("Alice",), ("Bob",)]


def test_execute_invalid_sql_returns_none(db_path):
    result = execute_queries(db_path, "SELECT Nonexistent_Column FROM singer")
    assert result is None


def test_compare_execution_identical_queries_match(db_path):
    q1 = "SELECT Name FROM singer WHERE Country = 'France'"
    q2 = "SELECT Name FROM singer WHERE Country = 'France'"
    assert compare_execution(db_path, q1, q2) is True


def test_compare_execution_different_row_order_still_matches(db_path):
    # set() comparison in compare_execution should treat row order as irrelevant
    q1 = "SELECT Name FROM singer WHERE Country = 'France' ORDER BY Age ASC"
    q2 = "SELECT Name FROM singer WHERE Country = 'France' ORDER BY Age DESC"
    assert compare_execution(db_path, q1, q2) is True


def test_compare_execution_different_results_do_not_match(db_path):
    q1 = "SELECT Name FROM singer WHERE Country = 'France'"
    q2 = "SELECT Name FROM singer WHERE Country = 'USA'"
    assert compare_execution(db_path, q1, q2) is False


def test_compare_execution_invalid_gold_sql_returns_false(db_path):
    # This is the exact bug found earlier: compare_execution originally only
    # guarded against gen_res being None, not ac_res. Locking that fix in.
    valid_sql = "SELECT Name FROM singer"
    invalid_sql = "SELECT Nonexistent_Column FROM singer"
    assert compare_execution(db_path, invalid_sql, valid_sql) is False
    assert compare_execution(db_path, valid_sql, invalid_sql) is False