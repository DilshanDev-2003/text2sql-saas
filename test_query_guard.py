import pytest
from query_guard import guard_readonly

def test_plain_select_passes():
  guard_readonly("SELECT * FROM singer")  # should not raise

def test_select_with_where_passes():
  guard_readonly("SELECT name FROM singer WHERE age > 30")

def test_case_insensitive_select_passes():
  guard_readonly("select * from singer")

def test_leading_whitespace_select_passes():
  guard_readonly("   \n  SELECT * FROM singer")

def test_insert_rejected():
  with pytest.raises(PermissionError):
    guard_readonly("INSERT INTO singer (name) VALUES ('X')")

def test_update_rejected():
  with pytest.raises(PermissionError):
    guard_readonly("UPDATE singer SET age = 40 WHERE name = 'X'")

def test_delete_rejected():
  with pytest.raises(PermissionError):
    guard_readonly("DELETE FROM singer")

def test_drop_rejected():
  with pytest.raises(PermissionError):
    guard_readonly("DROP TABLE singer")

def test_select_disguising_a_delete_rejected():
  # a CTE that starts with SELECT but contains a nested DELETE — first-word
  # check alone would miss this, which is why guard_readonly also scans the
  # full query for disallowed keywords, not just the first word
  sql = "WITH x AS (DELETE FROM singer RETURNING *) SELECT * FROM x"
  with pytest.raises(PermissionError):
    guard_readonly(sql)

def test_empty_string_rejected():
  with pytest.raises(PermissionError):
    guard_readonly("")