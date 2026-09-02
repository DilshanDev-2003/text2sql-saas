import sqlglot
from sqlglot.expressions import Table, Column

"""
query = "SELECT name, age FROM singer WHERE country = 'France'"
parsed = sqlglot.parse_one(query)

tables = list(parsed.find_all(Table))
for t in tables:
  print(t)

columns = list(parsed.find_all(Column))
for c in columns:
  print(c)  


query2 = "SELECT T1.name, T1.age FROM singer AS T1 JOIN concert AS T2 ON T1.id = T2.singer_id"
parsed2 = sqlglot.parse_one(query2)

tables2 = list(parsed2.find_all(Table))
alias_map = {}
for t in tables2:
  alias_map[t.alias or t.name] = t.name
print(alias_map)  

columns2 = list(parsed2.find_all(Column))
for c in columns2:
  alias = c.table
  real_table = alias_map.get(alias, alias)
  print(f"{c.name} -> table: {real_table}")


from schema_validation import validate_sql

example_schema_str = "stadium : Stadium_ID (number) , Location (text) , Name (text) , Capacity (number) , Highest (number) , Lowest (number) , Average (number) | singer : Singer_ID (number) , Name (text) , Country (text) , Song_Name (text) , Song_release_year (text) , Age (number) , Is_male (others) | concert : concert_ID (number) , concert_Name (text) , Theme (text) , Stadium_ID (text) , Year (text) | singer_in_concert : concert_ID (number) , Singer_ID (text)"

good_sql = "SELECT name, age FROM singer WHERE country = 'France'"
bad_sql = "SELECT TS_age FROM singer WHERE country = 'France'"

fake_schema_lookup = {
    "concert_singer": {"Schema (values (type))": example_schema_str}
}

is_valid, problems = validate_sql(good_sql, "concert_singer", fake_schema_lookup)
print("GOOD SQL:", is_valid, problems)

is_valid, problems = validate_sql(bad_sql, "concert_singer", fake_schema_lookup)
print("BAD SQL:", is_valid, problems)

real_bad_examples = [
    ("SELECT avg(TS_age) , min(TS_age) , max(TS_age) FROM singer WHERE country = 'France'", "concert_singer"),
]

for sql, db_id in real_bad_examples:
    is_valid, problems = validate_sql(sql, db_id, fake_schema_lookup)
    print("SQL:", sql)
    print("VALID:", is_valid, "PROBLEMS:", problems)
    print("---")

ambiguous_test = "SELECT Stadium_ID FROM stadium JOIN concert ON stadium.Stadium_ID = concert.Stadium_ID"

is_valid, problems = validate_sql(ambiguous_test, "concert_singer", fake_schema_lookup)
print("VALID:", is_valid, "PROBLEMS:", problems)   
"""

# explore.py or a fresh test file
from schema_validation import validate_sql, parse_schema_string
from db_runner import execute_queries, compare_execution
from model_utils import generate_sql, format_schema
from inference import generate_sql_query_with_retry, generate_sql_final, generate_candidates, voting_candidates, is_reasonable_query

print("all imports OK")