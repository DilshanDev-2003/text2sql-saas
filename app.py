from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text
import time
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from model_loader import load_model, get_model_and_tokenizer
from config import get_connection_string
from inference import generate_sql_final, _live_executor
from db_connection import get_engine, get_live_schema, get_sqlglot_dialect
from request_logger import log_request
from rate_limit import limiter, GENERATE_LIMIT, SCHEMA_LIMIT, generation_semaphore
from auth import require_api_key

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

# Registering the limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

class GenerateRequest(BaseModel):
  question: str
  n: int = 5

class GenerateResponse(BaseModel):
  sql: str
  result: list | None

@app.post("/generate", response_model=GenerateResponse)
@limiter.limit(GENERATE_LIMIT)
async def generate(request: Request, response: Response, req: GenerateRequest, tenant_id: int = Depends(require_api_key)):
  model, tokenizer = get_model_and_tokenizer()
  start = time.time()

  if generation_semaphore.locked():
    duration = time.time() - start
    log_request(req.question, req.n, duration, 503, error="gpu_busy")
    raise HTTPException(
      status_code=503,
      detail="The server is busy processing another request.Try again shortly.",
      headers={"Retry-After": "5"},
    )

  async with generation_semaphore:
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
      duration = time.time() - start
      log_request(req.question, req.n, duration, 500, error="unexpected_error")
      raise HTTPException(status_code=500, detail="Something went wrong while generating a response.")

    duration = time.time() - start

    if output["result"] is None:
      if output.get("failure_reason") == "db_unavailable":
        log_request(req.question, req.n, duration, 503, sql=output["sql"], error="db_unavailable")
        raise HTTPException(
          status_code=503,
          detail={
            "message": "The database is temporarily unavailable. Try again shortly.",
            "attempted_sql": output["sql"],
          },
        )
      log_request(req.question, req.n, duration, 422, sql=output["sql"], error="generation_failed")
      raise HTTPException(
        status_code=422,
        detail={
          "message": "Couldn't create a query that validated and executed successfully.",
          "attempted_sql": output["sql"],
        },
      )

    log_request(req.question, req.n, duration, 200, sql=output["sql"])
    return GenerateResponse(sql=output["sql"], result=output["result"])  

# Health Endpoint
@app.get("/health")
async def health():
  """
    Verifies that the model and the database connection are actually usable rather than just running.
    A simple query and the model and tokenizer loading are enough to test those.
  """
  model_ok = _model_loaded_and_ready()
  db_ok = _db_reachable()

  status = "ok" if (model_ok and db_ok) else "degraded"
  return {
    "status": status,
    "model": "ok" if model_ok else "unavailable",
    "database": "ok" if db_ok else "unreachable"
  }

def _model_loaded_and_ready():
  try:
    get_model_and_tokenizer()
    return True
  except RuntimeError:
    return False

def _db_reachable():
  try:
    with _engine.connect() as connection:
      connection.execute(text("SELECT 1"))       
    return True
  except Exception:
    return False

# Schema Endpoint
@app.get("/schema")
@limiter.limit(SCHEMA_LIMIT)
async def schema(request: Request, response: Response, tenant_id: int = Depends(require_api_key)):
  """
    Returns the live database's schema(e.g., tables, column names with types, primary keys, and foreign keys.)
  """  
  return _live_schema