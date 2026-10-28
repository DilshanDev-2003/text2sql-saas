import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.api.errors import connection_http_error
from app.api.schemas import GenerateRequest, GenerateResponse
from app.auth.dependencies import get_control_plane_engine, require_user
from app.core.encryption import get_encryptor
from app.core.rate_limit import GENERATE_LIMIT, generation_semaphore, limiter
from app.core.request_logger import log_request
from app.db.connection import get_sqlglot_dialect
from app.db.connection_safety import UnsafeConnectionError
from app.services import connections
from app.services.connections import ConnectionServiceError
from app.services.inference import _live_executor, generate_sql_final
from app.services.model_loader import get_model_and_tokenizer

router = APIRouter()


@router.post("/generate", response_model=GenerateResponse)
@limiter.limit(GENERATE_LIMIT)
async def generate(
  request: Request,
  response: Response,
  req: GenerateRequest,
  user_id: int = Depends(require_user),
):
  start = time.time()

  try:
    entry = await run_in_threadpool(
      connections.get_connection_entry,
      get_control_plane_engine(),
      request.app.state.connection_cache,
      get_encryptor(),
      user_id,
      req.connection_id,
    )
  except (ConnectionServiceError, UnsafeConnectionError) as error:
    http_error = connection_http_error(error)
    log_request(req.question, req.n, time.time() - start, http_error.status_code, error="connection_error")
    raise http_error from None

  model, tokenizer = get_model_and_tokenizer()

  if generation_semaphore.locked():
    log_request(req.question, req.n, time.time() - start, 503, error="gpu_busy")
    raise HTTPException(
      status_code=503,
      detail="The server is busy processing another request. Try again shortly.",
      headers={"Retry-After": "5"},
    )

  async with generation_semaphore:
    try:
      output = await run_in_threadpool(
        generate_sql_final,
        model,
        tokenizer,
        req.question,
        db_id=None,
        schema_lookup=None,
        executor=_live_executor(entry.engine),
        live_schema=entry.schema,
        dialect=get_sqlglot_dialect(entry.engine),
        n=req.n,
      )
    except Exception:
      log_request(req.question, req.n, time.time() - start, 500, error="unexpected_error")
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