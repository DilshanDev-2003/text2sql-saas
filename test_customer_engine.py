from unittest.mock import patch

from app.db.connection import build_customer_engine
from app.db.connection_safety import validate_connection_string


def make_target():
  def resolver(host, port, type=0):
    return [(0, 0, 0, "", ("93.184.216.34", port))]

  return validate_connection_string("postgresql://u:p@db.example.com/appdb", resolver)


def test_customer_engine_pins_validated_address():
  target = make_target()
  with patch("app.db.connection.create_engine") as create:
    build_customer_engine(target)

  assert create.call_args.args[0] == target.url
  assert create.call_args.kwargs["connect_args"]["hostaddr"] == "93.184.216.34"


def test_customer_engine_is_small_and_read_only_by_default():
  with patch("app.db.connection.create_engine") as create:
    build_customer_engine(make_target())

  kwargs = create.call_args.kwargs
  assert kwargs["pool_size"] == 2
  assert kwargs["max_overflow"] == 0
  assert kwargs["pool_pre_ping"] is True
  assert kwargs["connect_args"]["connect_timeout"] == 5
  options = kwargs["connect_args"]["options"]
  assert "statement_timeout=5000" in options
  assert "default_transaction_read_only=on" in options