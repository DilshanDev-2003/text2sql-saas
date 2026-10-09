import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.api.schemas import GenerateRequest, GenerateResponse
from app.auth.dependencies import require_api_key
from app.core.rate_limit import limiter, GENERATE_LIMIT, generation_semaphore
from app.core.request_logger import log_request
from app.services.inference import generate_sql_final, _live_executor
from app.services.model_loader import get_model_and_tokenizer

router = APIRouter()


@router.post("/generate", response_model=GenerateResponse)
@limiter.limit(GENERATE_LIMIT)
async def generate(request: Request, response: Response, req: GenerateRequest, tenant_id: int = Depends(require_api_key)):
  model, tokenizer = get_model_and_tokenizer()
  start = time.time()

  if generation_semaphore.locked():
    duration = time.time() - start
    log_request(req.question, req.n, duration, 503, error="gpu_busy")
    raise HTTPException(
      status_code=503,
      detail="The server is busy processing another request. Try again shortly.",
      headers={"Retry-After": "5"},
    )

  async with generation_semaphore:
    try:
      output = await run_in_threadpool(
        generate_sql_final,
        model, tokenizer, req.question,
        db_id=None, schema_lookup=None,
        executor=_live_executor(request.app.state.engine),
        live_schema=request.app.state.live_schema,
        dialect=request.app.state.dialect,
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