from unittest.mock import MagicMock

from app.services.connection_cache import ConnectionCache


class Clock:
  def __init__(self):
    self.now = 0.0

  def __call__(self):
    return self.now


def make(max_size=2, ttl=10):
  clock = Clock()
  return ConnectionCache(max_size, ttl, clock), clock


def test_get_missing_returns_none():
  cache, _ = make()
  assert cache.get(1) is None


def test_put_then_get_returns_the_same_engine_and_schema():
  cache, _ = make()
  engine = MagicMock()
  cache.put(1, engine, {"singer": {}})

  entry = cache.get(1)
  assert entry.engine is engine
  assert entry.schema == {"singer": {}}


def test_entry_within_ttl_is_returned():
  cache, clock = make(ttl=10)
  cache.put(1, MagicMock(), {})
  clock.now = 9
  assert cache.get(1) is not None


def test_expired_entry_is_removed_and_disposed():
  cache, clock = make(ttl=10)
  engine = MagicMock()
  cache.put(1, engine, {})
  clock.now = 11

  assert cache.get(1) is None
  engine.dispose.assert_called_once()
  assert cache.get(1) is None


def test_least_recently_used_entry_is_evicted_and_disposed():
  cache, _ = make(max_size=2)
  first, second, third = MagicMock(), MagicMock(), MagicMock()
  cache.put(1, first, {})
  cache.put(2, second, {})
  cache.put(3, third, {})

  assert cache.get(1) is None
  first.dispose.assert_called_once()
  assert cache.get(2) is not None
  assert cache.get(3) is not None


def test_get_refreshes_recency():
  cache, _ = make(max_size=2)
  first, second = MagicMock(), MagicMock()
  cache.put(1, first, {})
  cache.put(2, second, {})
  cache.get(1)
  cache.put(3, MagicMock(), {})

  assert cache.get(1) is not None
  assert cache.get(2) is None
  second.dispose.assert_called_once()


def test_evict_removes_and_disposes():
  cache, _ = make()
  engine = MagicMock()
  cache.put(1, engine, {})
  cache.evict(1)

  assert cache.get(1) is None
  engine.dispose.assert_called_once()


def test_evict_unknown_is_a_no_op():
  cache, _ = make()
  cache.evict(99)


def test_clear_disposes_everything():
  cache, _ = make()
  first, second = MagicMock(), MagicMock()
  cache.put(1, first, {})
  cache.put(2, second, {})
  cache.clear()

  first.dispose.assert_called_once()
  second.dispose.assert_called_once()
  assert cache.get(1) is None


def test_replacing_an_entry_disposes_the_old_engine():
  cache, _ = make()
  old, new = MagicMock(), MagicMock()
  cache.put(1, old, {})
  cache.put(1, new, {})

  old.dispose.assert_called_once()
  assert cache.get(1).engine is new


def test_putting_the_same_engine_again_does_not_dispose_it():
  cache, _ = make()
  engine = MagicMock()
  cache.put(1, engine, {})
  cache.put(1, engine, {"singer": {}})

  engine.dispose.assert_not_called()


def test_dispose_failure_does_not_raise():
  cache, _ = make()
  engine = MagicMock()
  engine.dispose.side_effect = RuntimeError("boom")
  cache.put(1, engine, {})
  cache.evict(1)