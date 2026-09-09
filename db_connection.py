from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

def get_engine(connection_string: str, statement_timeout_ms: int = 5000) -> Engine:
  """
    Creates a SQLAlchemy engine for any supported database with connection_string.
    e.g : "postgresql://user:password@host:port/database_name"
  """
  connect_args = {}
  if connection_string.startswith("postgresql"):
    connect_args["options"] = f"-c statement_timeout={statement_timeout_ms}"

  return create_engine(
    connection_string,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args=connect_args,
    )

def get_live_schema(engine):
  """
    Get a database's live schema.
  """

  inspector = inspect(engine)
  schema = {}

  for table_name in inspector.get_table_names():
    columns = inspector.get_columns(table_name)
    pk = inspector.get_pk_constraint(table_name)
    fks = inspector.get_foreign_keys(table_name)

    schema[table_name] = {
      "columns": [{"name": col["name"], "type": str(col["type"])} for col in columns],
      "primary_key": pk.get("constrained_columns", []),
      "foreign_keys": [
        {"columns": fk["constrained_columns"], "references": fk["referred_table"]}
        for fk in fks
      ],
    }

  return schema  

SQLALCHEMY_TO_SQLGLOT_DIALECT = {
  "postgresql": "postgres",
  "mysql": "mysql",
  "sqlite": "sqlite",
  "snowflake": "snowflake",
  "bigquery": "bigquery",
}

def get_sqlglot_dialect(engine: Engine) -> str:
  """
    Maps a SQLAlchemy engine's dialect name to sqlglot's expected name.
  """
  name = engine.dialect.name
  if name not in SQLALCHEMY_TO_SQLGLOT_DIALECT:
    raise ValueError(f"No sqlglot dialect mapping for sqlalchemy dialect: {name!r}")
  else:
    return SQLALCHEMY_TO_SQLGLOT_DIALECT[name]