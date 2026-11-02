import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.connections import router as connections_router
from app.api.routes.generate import router as generate_router
from app.api.routes.health import router as health_router
from app.auth.dependencies import get_control_plane_engine, require_user
from app.auth.oauth_routes import router as oauth_router
from app.auth.routes import router as auth_router
from app.core.config import get_session_secret
from app.core.rate_limit import limiter
from app.core.startup_checks import (
  check_control_plane,
  check_encryption,
  check_environment,
  raise_if_problems,
)
from app.services.connection_cache import ConnectionCache
from app.services.model_loader import load_model

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
  app.state.connection_cache = ConnectionCache()

  if os.environ.get("SKIP_MODEL_LOAD") != "1":
    raise_if_problems(check_environment())
    raise_if_problems(check_encryption() + check_control_plane(get_control_plane_engine()))
    load_model()

  yield

  app.state.connection_cache.clear()


app = FastAPI(lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=get_session_secret())
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth_router)
app.include_router(oauth_router)
app.include_router(generate_router)
app.include_router(connections_router)
app.include_router(health_router)


@app.get("/me")
async def me(user_id: int = Depends(require_user)):
  return {"user_id": user_id}