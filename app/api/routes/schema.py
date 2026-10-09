from fastapi import APIRouter, Depends, Request, Response

from app.auth.dependencies import require_api_key
from app.core.rate_limit import limiter, SCHEMA_LIMIT

router = APIRouter()


@router.get("/schema")
@limiter.limit(SCHEMA_LIMIT)
async def schema(request: Request, response: Response, tenant_id: int = Depends(require_api_key)):
  """Returns the live database's schema (tables, columns with types, primary keys, foreign keys)."""
  return request.app.state.live_schema