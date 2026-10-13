from fastapi import APIRouter, HTTPException, Request
from authlib.integrations.starlette_client import OAuthError

from app.auth.oauth import get_oauth
from app.auth.routes import TokenResponse
from app.auth.security import create_access_token
from app.auth.users import find_or_create_oauth_user
from app.core.config import get_google_redirect_uri

router = APIRouter()


@router.get("/auth/google/login")
async def google_login(request: Request):
  return await get_oauth().google.authorize_redirect(request, get_google_redirect_uri())


@router.get("/auth/google/callback", response_model=TokenResponse)
async def google_callback(request: Request):
  try:
    token = await get_oauth().google.authorize_access_token(request)
  except OAuthError:
    raise HTTPException(status_code=400, detail="Google sign-in failed.")

  userinfo = token.get("userinfo")
  if not userinfo or not userinfo.get("email_verified"):
    raise HTTPException(status_code=400, detail="Google account email is not verified.")

  user_id = find_or_create_oauth_user("google", userinfo["sub"], userinfo["email"])
  return TokenResponse(access_token=create_access_token(user_id))