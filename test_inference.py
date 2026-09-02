from unittest.mock import patch

from inference import voting_candidates, is_reasonable_query, generate_candidates


# ---- Tests that need no mocking at all — pure logic ----

def test_vote_picks_majority_result():
    candidates = [
        {"sql": "query A", "result": [(1, 2)]},
        {"sql": "query B", "result": [(1, 2)]},
        {"sql": "query C", "result": [(9, 9)]},
    ]
    winner = voting_candidates(candidates)
    assert winner in ("query A", "query B")  # either is a valid "majority" pick


def test_vote_returns_none_on_empty_candidates():
    assert voting_candidates([]) is None


def test_vote_handles_single_candidate():
    candidates = [{"sql": "only query", "result": [(1,)]}]
    assert voting_candidates(candidates) == "only query"


def test_reasonable_query_accepts_normal_join():
    sql = "SELECT * FROM singer AS T1 JOIN concert AS T2 ON T1.id = T2.singer_id"
    assert is_reasonable_query(sql, max_tables=8) is True


def test_reasonable_query_rejects_runaway_join():
    # simulate the exact pathological case seen in eval: many repeated joins
    sql = "SELECT * FROM " + " JOIN ".join(f"t{i}" for i in range(20))
    assert is_reasonable_query(sql, max_tables=8) is False


# ---- Tests that need a mocked generate_sql ----

FAKE_SCHEMA_LOOKUP = {
    "concert_singer": {
        "Schema (values (type))": "singer : Singer_ID (number) , Name (text) , Country (text) , Age (number)"
    }
}


@patch("inference.execute_queries")
@patch("inference.generate_sql")
def test_generate_candidates_filters_invalid_sql(mock_generate_sql, mock_execute_queries):
    # script generate_sql to always return a query referencing a fake column
    mock_generate_sql.return_value = "SELECT nonexistent_col FROM singer"

    candidates = generate_candidates(
        model=None, tokenizer=None, question="irrelevant",
        db_id="concert_singer", schema_lookup=FAKE_SCHEMA_LOOKUP,
        db_path="irrelevant", n=3,
    )

    # every candidate should have been rejected by validate_sql, so none executed
    assert candidates == []
    mock_execute_queries.assert_not_called()


@patch("inference.execute_queries")
@patch("inference.generate_sql")
def test_generate_candidates_keeps_valid_executable_sql(mock_generate_sql, mock_execute_queries):
    mock_generate_sql.return_value = "SELECT Name FROM singer WHERE Country = 'France'"
    mock_execute_queries.return_value = [("Alice",)]

    candidates = generate_candidates(
        model=None, tokenizer=None, question="irrelevant",
        db_id="concert_singer", schema_lookup=FAKE_SCHEMA_LOOKUP,
        db_path="irrelevant", n=3,
    )

    assert len(candidates) == 3
    assert candidates[0]["result"] == [("Alice",)]