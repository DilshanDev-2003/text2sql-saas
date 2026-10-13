import logging
from typing import Protocol

from app.core.config import get_email_backend

logger = logging.getLogger(__name__)

class EmailSender(Protocol):
  def send(self, to: str, subject: str, body: str) -> None: ...

class ConsoleEmailSender:
  def send(self, to: str, subject: str, body: str) -> None:
    logger.info("EMAIL to=%s subject=%s\n%s", to, subject, body)

def get_email_sender() :
  backend = get_email_backend()
  if backend == "console":
    return ConsoleEmailSender()
  raise ValueError(f"Unknown EMAIL_BACKEND: {backend}")