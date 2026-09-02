import re
import sqlglot
from sqlglot.expressions import Table, Column

def normalize_quotes(sql):
    """
    Converts double-quoted string values to single-quoted, since SQLite
    treats double quotes ambiguously (identifier or string depending on
    context), while sqlglot's static parser can't resolve that ambiguity
    without schema awareness. Single quotes are unambiguous everywhere.
    """
    # matches a double-quoted segment and swaps the quote characters
    return re.sub(r'"([^"]*)"', r"'\1'", sql)

def parse_schema_string(schema_str):
  """
    Create schema as a String
  """
  tables = {}
  table_chunks = schema_str.split("|")
  for chunk in table_chunks:
    table_name, columns_part = chunk.split(":", 1)
    table_name = table_name.strip()
    col_names = []
    for col_entry in columns_part.split(","):
      col_entry = col_entry.strip()
      col_name = col_entry.split("(")[0].strip()
      col_names.append(col_name)
    tables[table_name] = col_names
  return tables 

def validate_sql(sql, db_id, schema_lookup):
  """
    Validating the sql
  """
  problems = []

  schema_row = schema_lookup[db_id]
  real_schema = parse_schema_string(schema_row["Schema (values (type))"])
  real_schema_lower = {
    table.lower(): [col.lower() for col in cols]
    for table, cols in real_schema.items()
  }
  real_table_names_lower = set(real_schema_lower.keys())

  try:
    parsed = sqlglot.parse_one(normalize_quotes(sql), read="sqlite")
  except Exception as e:
    return False, [f"Failed to parse SQL: {e}"]

  alias_map = {}
  for t in parsed.find_all(Table):
    alias_map[t.alias or t.name] = t.name
    if t.name.lower() not in real_table_names_lower:
      problems.append(f"Unknown Table: {t.name}")

  tables_in_query = set(v.lower() for v in alias_map.values())

  for c in parsed.find_all(Column):
    alias = c.table
    col_name_lower = c.name.lower()

    if alias == "":
      valid_in_any = any(
        col_name_lower in real_schema_lower.get(t, [])
        for t in tables_in_query
        )
      if not valid_in_any:
        problems.append(f"Unknown column: {c.name} (no table prefix, checked against {tables_in_query})")
      continue

    real_table = alias_map.get(alias, alias).lower()

    if real_table not in real_schema_lower:
      continue

    if col_name_lower not in real_schema_lower[real_table]:
      problems.append(f"Unknown column: {c.name} (on table {real_table})")

  is_valid = len(problems) == 0
  return is_valid, problems