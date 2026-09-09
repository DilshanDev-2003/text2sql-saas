DISALLOWED_KEYWORDS = {"insert", "update", "delete", "drop", "alter", "truncate", "grant", "create"}

def guard_readonly(sql: str) -> None:
  """
    Check there is disallowed words in the query in two ways.
      1. first keyword must be SELECT.
      2. disallowed any keyword from DISALLOWED_KEYWORDS.
  """
  stripped = sql.strip().lower()
  first_word = stripped.split(None, 1)[0] if stripped else ""

  if first_word != "select":
    raise PermissionError(f"Only SELECT queries are permitted, got: {first_word!r}")

  if any(kw in stripped for kw in DISALLOWED_KEYWORDS):
    raise PermissionError("Query contains a disallowed keyword")