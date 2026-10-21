CREATE TABLE db_connections (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  host TEXT NOT NULL,
  database_name TEXT NOT NULL,
  encrypted_connection_string BYTEA NOT NULL,
  key_version INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_connected_at TIMESTAMPTZ,
  UNIQUE (user_id, name)
);

CREATE INDEX idx_db_connections_user_id ON db_connections(user_id);