from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from config import get_rate_limit

def client_key(request: Request) -> str:
  return get_remote_address(request)

limiter = Limiter(key_func=client_key, headers_enabled=True, swallow_errors=False)

GENERATE_LIMIT = get_rate_limit("RATE_LIMIT_GENERATE", "10/minute")
SCHEMA_LIMIT = get_rate_limit("RATE_LIMIT_SCHEMA", "60/minute")