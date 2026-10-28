from fastapi import HTTPException

from app.db.connection_safety import UnsafeConnectionError
from app.services.connections import (
  ConnectionLimitReached,
  ConnectionNameTaken,
  ConnectionNotFound,
  ConnectionTestFailed,
  ConnectionUnreadable,
  InvalidConnectionName,
)

STATUS_BY_ERROR = {
  InvalidConnectionName: 422,
  UnsafeConnectionError: 400,
  ConnectionTestFailed: 400,
  ConnectionNotFound: 404,
  ConnectionNameTaken: 409,
  ConnectionLimitReached: 409,
  ConnectionUnreadable: 409,
}


def connection_http_error(error: Exception) -> HTTPException:
  return HTTPException(status_code=STATUS_BY_ERROR.get(type(error), 400), detail=str(error))