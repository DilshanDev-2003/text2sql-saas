from fastapi import APIRouter, Request
from sqlalchemy import text

from app.services.model_loader import get_model_and_tokenizer

router = APIRouter()


@router.get("/health")
async def health(request: Request):
  """Verifies the model and database connection are genuinely usable, not just that the process is running."""
  model_ok = _model_loaded_and_ready()
  db_ok = _db_reachable(request.app.state.engine)

  status = "ok" if (model_ok and db_ok) else "degraded"
  return {
    "status": status,
    "model": "ok" if model_ok else "unavailable",
    "database": "ok" if db_ok else "unreachable",
  }


def _model_loaded_and_ready():
  try:
    get_model_and_tokenizer()
    return True
  except RuntimeError:
    return False


def _db_reachable(engine):
  try:
    with engine.connect() as connection:
      connection.execute(text("SELECT 1"))
    return True
  except Exception:
    return False