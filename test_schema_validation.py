import pytest
from schema_validation import validate_sql, extract_column_names

# --- extract_column_names ---

def test_extract_column_names_flat_dict_passthrough():
  flat = {"singer": ["Name", "Age", "Country"]}
  assert extract_column_names(flat) == flat

def test_extract_column_names_live_typed_dict():
  live = {
    "singer": {
      "columns": [{"name": "Name", "type": "VARCHAR"}, {"name": "Age", "type": "INTEGER"}],
      "primary_key": ["Name"],
      "foreign_keys": [],
    }
  }
  assert extract_column_names(live) == {"singer": ["Name", "Age"]}

def test_extract_column_names_mixed_shapes():
  # a schema with one flat table and one live-typed table — normalizer
  # should handle both in the same call without special-casing per table
  mixed = {
    "singer": ["Name", "Age"],
    "concert": {"columns": [{"name": "Concert_ID", "type": "INTEGER"}], "primary_key": [], "foreign_keys": []},
  }
  assert extract_column_names(mixed) == {"singer": ["Name", "Age"], "concert": ["Concert_ID"]}


# --- validate_sql with live_schema ---

LIVE_SCHEMA = {
  "singer": {
    "columns": [
      {"name": "Singer_ID", "type": "INTEGER"},
      {"name": "Name", "type": "VARCHAR"},
      {"name": "Age", "type": "INTEGER"},
      {"name": "Country", "type": "VARCHAR"},
    ],
    "primary_key": ["Singer_ID"],
    "foreign_keys": [],
  },
  "concert": {
    "columns": [
      {"name": "Concert_ID", "type": "INTEGER"},
      {"name": "Singer_ID", "type": "INTEGER"},
    ],
    "primary_key": ["Concert_ID"],
    "foreign_keys": [{"columns": ["Singer_ID"], "references": "singer"}],
  },
}

def test_valid_sql_against_live_schema():
  sql = "SELECT Name, Age FROM singer WHERE Country = 'France'"
  is_valid, problems = validate_sql(sql, live_schema=LIVE_SCHEMA, dialect="postgres")
  assert is_valid
  assert problems == []

def test_unknown_column_against_live_schema():
  sql = "SELECT TS_age FROM singer"
  is_valid, problems = validate_sql(sql, live_schema=LIVE_SCHEMA, dialect="postgres")
  assert not is_valid
  assert any("TS_age" in p for p in problems)

def test_unknown_table_against_live_schema():
  sql = "SELECT * FROM nonexistent_table"
  is_valid, problems = validate_sql(sql, live_schema=LIVE_SCHEMA, dialect="postgres")
  assert not is_valid
  assert any("nonexistent_table" in p for p in problems)

def test_join_against_live_schema():
  sql = (
    "SELECT s.Name, c.Concert_ID FROM singer AS s "
    "JOIN concert AS c ON s.Singer_ID = c.Singer_ID"
  )
  is_valid, problems = validate_sql(sql, live_schema=LIVE_SCHEMA, dialect="postgres")
  assert is_valid

def test_live_schema_takes_priority_over_schema_lookup():
  # if both are somehow passed, live_schema should win — this is a
  # deliberate priority choice made in validate_sql, worth locking in
  bogus_lookup = {"some_db": {"Schema (values (type))": "other_table: X (int)"}}
  sql = "SELECT Name FROM singer"
  is_valid, problems = validate_sql(
    sql, db_id="some_db", schema_lookup=bogus_lookup, live_schema=LIVE_SCHEMA, dialect="postgres"
  )
  assert is_valid

def test_missing_schema_source_raises():
  with pytest.raises(ValueError):
    validate_sql("SELECT 1")