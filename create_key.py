from sqlalchemy import create_engine, text
from auth import generate_api_key, hash_api_key
from config import get_control_plane_connection_string

def create_api_key(tenant_name: str) -> str:
  engine = create_engine(get_control_plane_connection_string())
  key = generate_api_key()
  key_hash = hash_api_key(key)

  with engine.begin() as conn:
    tenant_id = conn.execute(
      text("INSERT INTO tenants (name) VALUES (:name) RETURNING id"),
      {"name": tenant_name},
    ).scalar_one()

    conn.execute(
      text("INSERT INTO api_keys (tenant_id, key_hash) VALUES (:tenant_id, :key_hash)"),
      {"tenant_id": tenant_id, "key_hash": key_hash}
    )

    return key

if __name__ == "__main__":
  import sys
  key = create_api_key(sys.argv[1])
  print(f"Save this key now - it will not be shown again:\n{key}")  