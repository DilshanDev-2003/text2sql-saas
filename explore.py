"""
import sqlglot
from sqlglot.expressions import Table, Column


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


# explore.py or a fresh test file
from schema_validation import validate_sql, parse_schema_string
from db_runner import execute_queries, compare_execution
from model_utils import generate_sql, format_schema
from inference import generate_sql_query_with_retry, generate_sql_final, generate_candidates, voting_candidates, is_reasonable_query

print("all imports OK")

# --- SEMANTIC LAYER ---
from semantic_layer import find_relevant_terms

result = find_relevant_terms("Who are the high performer singers?", "concert_singer")
print(result)

result2 = find_relevant_terms("What is the average age?", "concert_singer")
print(result2)
# -----------------------------------------------
question = "Who are the high performer singers?"
term = "high performer"
print(term.lower() in question.lower())
# -----------------------------------------------
from semantic_layer import SEMANTIC_TERMS
db_id = "concert_singer"
question = "Who are the high performer singers?"

terms_for_db = SEMANTIC_TERMS.get(db_id, {})
print("terms_for_db:", terms_for_db)

question_lower = question.lower()
print("question_lower:", question_lower)

for term, meaning in terms_for_db.items():
    print("checking term:", repr(term), "-> lower:", repr(term.lower()))
    print("is it in question?", term.lower() in question_lower)

from semantic_layer import find_relevant_terms

result = find_relevant_terms("Who are the high performer singers?", "concert_singer")
print(result)

from semantic_layer import inject_semantic_terms

context = inject_semantic_terms("Who are the high performer singers?", "concert_singer")
print(context)

context2 = inject_semantic_terms("What is the average age?", "concert_singer")
print(repr(context2))



# add a second term to the same database
add_new_term("concert_singer", "veteran performer", "Age > 50")

print(list_terms("concert_singer"))

# confirm both terms can be detected independently
print(find_relevant_terms("Who are the veteran performer singers?", "concert_singer"))
print(find_relevant_terms("Who are the high performer singers?", "concert_singer"))

# confirm removal works
remove_terms("concert_singer", "veteran performer")
print(list_terms("concert_singer"))


from semantic_layer import add_new_term, list_terms, find_relevant_terms, remove_terms, inject_semantic_terms

add_new_term("concert_singer", "veteran performer", "Age > 50")

question = "Compare high performer and veteran performer singers"
context = inject_semantic_terms(question, "concert_singer")
print(context)

remove_terms("concert_singer", "veteran performer")  # clean up after

from db_connection import get_engine, get_live_schema

engine = get_engine("postgresql://postgres:Dilshan&&123456@localhost:5432/text2sql_test")
schema = get_live_schema(engine)
print(schema)

from db_connection import get_engine
from db_runner import execute_live

engine = get_engine("postgresql://postgres:Dilshan&&123456@localhost:5432/text2sql_test")

result = execute_live(engine, "SELECT name FROM singer WHERE country = 'France'")
print(result)

bad_result = execute_live(engine, "SELECT nonexistent_column FROM singer")
print(bad_result)


from schema_validation import validate_sql
from db_connection import get_engine, get_live_schema

engine = get_engine("postgresql://postgres:Dilshan&&123456@localhost:5432/text2sql_test")
live_schema = get_live_schema(engine)

# wrap it the way validate_sql expects: {db_id: schema}
live_schema_lookup = {"text2sql_test": live_schema}

is_valid, problems = validate_sql("SELECT name FROM singer WHERE country = 'France'", "text2sql_test", live_schema_lookup)
print(is_valid, problems)

is_valid2, problems2 = validate_sql("SELECT nonexistent FROM singer", "text2sql_test", live_schema_lookup)
print(is_valid2, problems2)


# config.py get the connection string that wanted by the db_connection.py get_engine function.
from config import get_connection_string
from db_connection import get_engine

engine = get_engine(get_connection_string())


# This is how the pieces now connect for a live database.
from config import get_connection_string
from db_connection import get_engine, get_live_schema, get_sqlglot_dialect
from schema_validation import validate_sql

engine = get_engine(get_connection_string())
live_schema = get_live_schema(engine)
dialect = get_sqlglot_dialect(engine)
sql = "SELECT name FROM singer WHERE country = 'France'"
is_valid, problems = validate_sql(sql, live_schema=live_schema, dialect=dialect)
print("is valid: ", is_valid)
print("problems: ", problems)


# Usage for a live query.
from config import get_connection_string
from db_connection import get_engine, get_live_schema, get_sqlglot_dialect
from inference import generate_sql_final, _live_executor

engine = get_engine(get_connection_string())
live_schema = get_live_schema(engine)
dialect = get_sqlglot_dialect(engine)

sql = generate_sql_final(
  model, tokenizer, question="...", db_id=None, schema_lookup=None,
  executor=_live_executor(engine), live_schema=live_schema, dialect=dialect, n=5,
)

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

load_dotenv()
url = os.environ["CONTROL_PLANE_DATABASE_URL"]
print(make_url(url).host, make_url(url).database)

with create_engine(url).connect() as c:
  print([r[0] for r in c.execute(text(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"
  ))])

import requests

r = requests.post("http://localhost:8000/signup", json={"email": "verify-test@example.com", "password": "testpass123"})
print(r.status_code)

r = requests.post("http://localhost:8000/auth/verify-email", json={"token": "e7lKgYUjFqoiYCaVTtG0M7cPRAGvPNypMuubEELYIZ4"})
print(r.status_code, r.json())

import requests

r = requests.post("http://localhost:8000/signup", json={"email": "dilshanonline5@gmail.com", "password": "mypassword1"})
print(r.status_code)

r = requests.post("http://localhost:8000/auth/verify-email", json={"token": "gRiC3LvpMP4KKI9zCCB-XodK4P39j4QWOtX9HWXLZcw"})
print(r.status_code, r.json())

r = requests.post("http://localhost:8000/login", json={"email": "dilshanonline5@gmail.com", "password": "mypassword1"})
print(r.status_code)

import requests

r = requests.post("http://localhost:8000/signup", json={"email": "Case.Test@Example.COM", "password": "testpass123"})
print(r.status_code)
r = requests.post("http://localhost:8000/signup", json={"email": "case.test@example.com", "password": "testpass123"})
print(r.status_code)


import requests

codes = [
  requests.post("http://localhost:8000/login", json={"email": "nobody@example.com", "password": "x"}).status_code
  for _ in range(11)
]
print(codes)

import requests

base = "http://localhost:8000"
email = "alpha-test@examplex.com"
password = "Dilshan161218"

r = requests.post(f"{base}/signup", json={"email": email, "password": password})
print(r.status_code)

"""
import requests

base = "http://localhost:8000"
email = "alpha-test@examplex.com"
password = "Dilshan161218"

token = requests.post(f"{base}/login", json={"email": email, "password": password}).json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

good = "postgresql://neondb_owner:npg_sKCJ7i3qnXBT@ep-billowing-wildflower-b3syyenv.c-4.ap-southeast-1.aws.neon.tech/customer_test?sslmode=require&channel_binding=require"
for body in [
  {"name": "Test", "connection_string": good},
  {"name": "Test", "connection_string": good},
  {"name": "Local", "connection_string": "postgresql://u:p@localhost/db"},
  {"name": "Weak", "connection_string": good.split("?")[0] + "?sslmode=disable"},
]:
  r = requests.post(f"{base}/connections", headers=headers, json=body)
  print(r.status_code, r.json())

print(requests.get(f"{base}/connections", headers=headers).json())


