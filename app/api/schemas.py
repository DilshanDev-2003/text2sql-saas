from datetime import datetime
from pydantic import BaseModel, Field, SecretStr

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

MAX_CANDIDATES = 10
class GenerateRequest(BaseModel):
  connection_id: int
  question: str = Field(min_length=1, max_length=2000)
  n: int = Field(default=5, ge=1, le=MAX_CANDIDATES)  