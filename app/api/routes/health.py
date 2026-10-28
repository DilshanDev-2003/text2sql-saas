from fastapi import APIRouter, Request
from sqlalchemy import text

from app.auth.dependencies import get_control_plane_engine
from app.services.model_loader import get_model_and_tokenizer

router = APIRouter()


@router.get("/health")
async def health(request: Request):
  """Verifies the model and database connection are genuinely usable, not just that the process is running."""
  model_ok = _model_loaded_and_ready()
  control_plane_ok = _control_plane_reachable()

  return {
    "status": "ok" if (model_ok and control_plane_ok) else "degraded",
    "model": "ok" if model_ok else "unavailable",
    "control_plane": "ok" if control_plane_ok else "unreachable",
  }


def _model_loaded_and_ready() -> bool:
  try:
    get_model_and_tokenizer()
    return True
  except RuntimeError:
    return False


def _control_plane_reachable() -> bool:
  try:
    with get_control_plane_engine().connect() as connection:
      connection.execute(text("SELECT 1"))
    return True
  except Exception:
    return False