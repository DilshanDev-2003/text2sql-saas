import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.services.model_loader import load_model
from app.core.config import get_connection_string
from app.db.connection import get_engine, get_live_schema, get_sqlglot_dialect
from app.core.rate_limit import limiter
from app.auth.dependencies import require_user
from app.auth.routes import router as auth_router
from app.api.routes.generate import router as generate_router
from app.api.routes.schema import router as schema_router
from app.api.routes.health import router as health_router
from starlette.middleware.sessions import SessionMiddleware
from app.core.config import get_session_secret
from app.auth.oauth_routes import router as oauth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
  """Loads the model and connects to the live database once at startup."""
  if os.environ.get("SKIP_MODEL_LOAD") != "1":
    load_model()
    app.state.engine = get_engine(get_connection_string())
    app.state.live_schema = get_live_schema(app.state.engine)
    app.state.dialect = get_sqlglot_dialect(app.state.engine)

  yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=get_session_secret())
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


app.include_router(auth_router)
app.include_router(generate_router)
app.include_router(schema_router)
app.include_router(health_router)
app.include_router(oauth_router)


@app.get("/me")
async def me(user_id: int = Depends(require_user)):
  return {"user_id": user_id}