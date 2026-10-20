from typing import Annotated

from pydantic import AfterValidator, EmailStr

def normalize_email(email: str) -> str:
  return email.strip().lower()

NormalizedEmail = Annotated[EmailStr, AfterValidator(normalize_email)]