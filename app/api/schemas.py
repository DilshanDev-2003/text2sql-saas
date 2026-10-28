from datetime import datetime
from pydantic import BaseModel, SecretStr

class GenerateRequest(BaseModel):
  question: str
  n: int = 5

class GenerateResponse(BaseModel):
  sql: str
  result: list | None

class CreateConnectionRequest(BaseModel):
  name: str
  connection_string: SecretStr

class ConnectionOut(BaseModel):
  id: int
  name: str
  host: str
  database_name: str
  created_at: datetime
  last_connected_at: datetime | None = None  