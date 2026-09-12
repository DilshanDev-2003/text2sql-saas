from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from model_loader import load_model, get_model_and_tokenizer
from config import get_connection_string
from inference import generate_sql_final, _live_executor
from db_connection import get_engine, get_live_schema, get_sqlglot_dialect

_engine = None
_live_schema = None
_dialect = None

@asynccontextmanager
async def lifespan(app: FastAPI):
  """
    When the server starts to run, at that moment the model is loaded to the RAM/GPU. Why this: Before a user send a request we must load the model. If not user has to wait for model to load. 
  """
  global _engine, _live_schema, _dialect
  
  load_model()

  _engine = get_engine(get_connection_string())
  _live_schema = get_live_schema(_engine)
  _dialect = get_sqlglot_dialect(_engine)

  yield

app = FastAPI(lifespan=lifespan)

class GenerateRequest(BaseModel):
  question: str
  n: int = 5

class GenerateResponse(BaseModel):
  sql: str
  result: list | None

@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
  model, tokenizer = get_model_and_tokenizer()
  try: 
    output = await run_in_threadpool(
      generate_sql_final,
      model, tokenizer, req.question,
      db_id=None, schema_lookup=None,
      executor=_live_executor(_engine),
      live_schema=_live_schema,
      dialect=_dialect,
      n=req.n,
    )    
  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))

  return GenerateResponse(sql=output["sql"], result=output["result"])  

@app.get("/health")
async def health():
  return {"status": "ok"}