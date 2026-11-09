from dataclasses import dataclass

from app.core.config import get_max_result_bytes, get_max_result_rows


@dataclass(frozen=True)
class CappedRows:
  rows: list[tuple]
  truncated: bool


def read_capped(result, max_rows=None, max_bytes=None, batch_size=200) -> CappedRows:
  max_rows = get_max_result_rows() if max_rows is None else max_rows
  max_bytes = get_max_result_bytes() if max_bytes is None else max_bytes

  rows = []
  size = 0
  while True:
    batch = result.fetchmany(min(batch_size, max_rows + 1 - len(rows)))
    if not batch:
      return CappedRows(rows, False)
    for raw in batch:
      row = tuple(raw)
      size += len(repr(row))
      if len(rows) >= max_rows or size > max_bytes:
        return CappedRows(rows, True)
      rows.append(row)