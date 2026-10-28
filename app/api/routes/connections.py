from fastapi import APIRouter, Depends, Request, Response

from app.api.errors import connection_http_error
from app.api.schemas import ConnectionOut, CreateConnectionRequest
from app.auth.dependencies import get_control_plane_engine, require_user, require_verified_user
from app.core.encryption import get_encryptor
from app.core.rate_limit import CONNECTIONS_CREATE_LIMIT, CONNECTIONS_LIMIT, limiter
from app.db.connection_safety import UnsafeConnectionError
from app.services import connections
from app.services.connections import ConnectionServiceError

router = APIRouter()


@router.post("/connections", response_model=ConnectionOut, status_code=201)
@limiter.limit(CONNECTIONS_CREATE_LIMIT)
def add_connection(
  request: Request, response: Response, req: CreateConnectionRequest, user_id: int = Depends(require_verified_user),):
  try:
    return connections.create_connection(
      get_control_plane_engine(),
      user_id,
      req.name,
      req.connection_string.get_secret_value(),
      get_encryptor(),
      request.app.state.connection_cache,
    )
  except (ConnectionServiceError, UnsafeConnectionError) as error:
    raise connection_http_error(error) from None


@router.get("/connections", response_model=list[ConnectionOut])
@limiter.limit(CONNECTIONS_LIMIT)
def get_connections(request: Request, response: Response, user_id: int = Depends(require_user)):
  return connections.list_connections(get_control_plane_engine(), user_id)


@router.delete("/connections/{connection_id}", status_code=204)
@limiter.limit(CONNECTIONS_LIMIT)
def remove_connection(request: Request, response: Response, connection_id: int, user_id: int = Depends(require_user),):
  try:
    connections.delete_connection(
      get_control_plane_engine(),
      request.app.state.connection_cache,
      user_id,
      connection_id,
    )
  except ConnectionServiceError as error:
    raise connection_http_error(error) from None

@router.get("/connections/{connection_id}/schema")
@limiter.limit(CONNECTIONS_LIMIT)
def get_connection_schema(request: Request, response: Response, connection_id: int, user_id: int = Depends(require_user),):
  try:
    entry = connections.get_connection_entry(
      get_control_plane_engine(),
      request.app.state.connection_cache,
      get_encryptor,
      user_id,
      connection_id,
    )  
  except (ConnectionServiceError, UnsafeConnectionError) as error:
    raise connection_http_error(error) from None
  return entry.schema