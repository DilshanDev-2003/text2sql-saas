from pydantic import BaseModel

class GenerateRequest(BaseModel):
  question: str
  n: int = 5

class GenerateResponse(BaseModel):
  sql: str
  result: list | None