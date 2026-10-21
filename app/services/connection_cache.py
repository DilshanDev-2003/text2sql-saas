import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class CachedConnection:
  engine: Any
  schema: dict
  loaded_at: float


def _dispose(entries: list[CachedConnection]) -> None:
  for entry in entries:
    try:
      entry.engine.dispose()
    except Exception:
      logger.warning("Failed to dispose a cached engine", exc_info=True)


class ConnectionCache:
  def __init__(
    self,
    max_size: int = 20,
    ttl_seconds: float = 600,
    clock: Callable[[], float] = time.monotonic,
  ):
    self._max_size = max_size
    self._ttl = ttl_seconds
    self._clock = clock
    self._entries: OrderedDict[int, CachedConnection] = OrderedDict()
    self._lock = threading.Lock()

  def get(self, connection_id: int) -> CachedConnection | None:
    expired = None
    with self._lock:
      entry = self._entries.get(connection_id)
      if entry is None:
        return None
      if self._clock() - entry.loaded_at > self._ttl:
        expired = self._entries.pop(connection_id)
      else:
        self._entries.move_to_end(connection_id)
        return entry
    _dispose([expired])
    return None

  def put(self, connection_id: int, engine: Any, schema: dict) -> CachedConnection:
    entry = CachedConnection(engine, schema, self._clock())
    to_dispose = []
    with self._lock:
      replaced = self._entries.pop(connection_id, None)
      if replaced is not None and replaced.engine is not engine:
        to_dispose.append(replaced)
      self._entries[connection_id] = entry
      while len(self._entries) > self._max_size:
        _, oldest = self._entries.popitem(last=False)
        to_dispose.append(oldest)
    _dispose(to_dispose)
    return entry

  def evict(self, connection_id: int) -> None:
    with self._lock:
      entry = self._entries.pop(connection_id, None)
    if entry is not None:
      _dispose([entry])

  def clear(self) -> None:
    with self._lock:
      entries = list(self._entries.values())
      self._entries.clear()
    _dispose(entries)