from schema_validation import validate_sql, parse_schema_string


# Reusable test schema — same concert_singer schema you've used all along.
SCHEMA_STR = (
    "stadium : Stadium_ID (number) , Location (text) , Name (text) , Capacity (number) , "
    "Highest (number) , Lowest (number) , Average (number) | "
    "singer : Singer_ID (number) , Name (text) , Country (text) , Song_Name (text) , "
    "Song_release_year (text) , Age (number) , Is_male (others) | "
    "concert : concert_ID (number) , concert_Name (text) , Theme (text) , Stadium_ID (text) , Year (text) | "
    "singer_in_concert : concert_ID (number) , Singer_ID (text)"
)

SCHEMA_LOOKUP = {
    "concert_singer": {"Schema (values (type))": SCHEMA_STR}
}


def test_valid_query_passes():
    sql = "SELECT name, age FROM singer WHERE country = 'France'"
    is_valid, problems = validate_sql(sql, "concert_singer", SCHEMA_LOOKUP)
    assert is_valid is True
    assert problems == []


def test_hallucinated_column_fails():
    sql = "SELECT TS_age FROM singer WHERE country = 'France'"
    is_valid, problems = validate_sql(sql, "concert_singer", SCHEMA_LOOKUP)
    assert is_valid is False
    assert any("TS_age" in p for p in problems)


def test_case_insensitive_columns_pass():
    sql = "SELECT NAME, AGE FROM SINGER WHERE COUNTRY = 'France'"
    is_valid, problems = validate_sql(sql, "concert_singer", SCHEMA_LOOKUP)
    assert is_valid is True


def test_double_quoted_string_not_mistaken_for_column():
    sql = 'SELECT avg(Age) FROM singer WHERE Country = "France"'
    is_valid, problems = validate_sql(sql, "concert_singer", SCHEMA_LOOKUP)
    assert is_valid is True


def test_unknown_table_fails():
    sql = "SELECT * FROM nonexistent_table"
    is_valid, problems = validate_sql(sql, "concert_singer", SCHEMA_LOOKUP)
    assert is_valid is False
    assert any("nonexistent_table" in p for p in problems)


def test_ambiguous_but_real_column_across_join_passes():
    # Stadium_ID exists on both stadium and concert — should NOT be flagged,
    # since it genuinely exists (this is the edge case from earlier tonight).
    sql = "SELECT Stadium_ID FROM stadium JOIN concert ON stadium.Stadium_ID = concert.Stadium_ID"
    is_valid, problems = validate_sql(sql, "concert_singer", SCHEMA_LOOKUP)
    assert is_valid is True


def test_parse_schema_string_basic():
    result = parse_schema_string(SCHEMA_STR)
    assert "singer" in result
    assert "Age" in result["singer"]
    assert "Stadium_ID" in result["stadium"]