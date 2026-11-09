from app.db.result_limits import read_capped


class FakeResult:
  def __init__(self, rows):
    self._rows = list(rows)
    self.fetch_sizes = []

  def fetchmany(self, size):
    self.fetch_sizes.append(size)
    batch, self._rows = self._rows[:size], self._rows[size:]
    return batch


def test_fewer_rows_than_the_cap_are_all_returned():
  capped = read_capped(FakeResult([[1], [2], [3]]), max_rows=10, max_bytes=10_000)

  assert capped.rows == [(1,), (2,), (3,)]
  assert capped.truncated is False


def test_exactly_the_cap_is_not_truncated():
  capped = read_capped(FakeResult([[i] for i in range(5)]), max_rows=5, max_bytes=10_000)

  assert len(capped.rows) == 5
  assert capped.truncated is False


def test_one_row_over_the_cap_is_truncated():
  capped = read_capped(FakeResult([[i] for i in range(6)]), max_rows=5, max_bytes=10_000)

  assert len(capped.rows) == 5
  assert capped.truncated is True


def test_stops_reading_instead_of_draining_the_cursor():
  result = FakeResult([[i] for i in range(10_000)])

  capped = read_capped(result, max_rows=50, max_bytes=1_000_000, batch_size=20)

  assert capped.truncated is True
  assert sum(result.fetch_sizes) <= 51
  assert len(result._rows) > 9_000


def test_byte_budget_truncates_before_the_row_cap():
  rows = [["x" * 100] for _ in range(10)]

  capped = read_capped(FakeResult(rows), max_rows=1000, max_bytes=250)

  assert len(capped.rows) == 2
  assert capped.truncated is True


def test_a_single_oversized_row_gives_an_empty_truncated_result():
  capped = read_capped(FakeResult([["x" * 500]]), max_rows=10, max_bytes=100)

  assert capped.rows == []
  assert capped.truncated is True


def test_empty_result_is_not_truncated():
  capped = read_capped(FakeResult([]), max_rows=10, max_bytes=100)

  assert capped.rows == []
  assert capped.truncated is False


def test_reads_across_several_batches():
  result = FakeResult([[i] for i in range(5)])

  capped = read_capped(result, max_rows=10, max_bytes=10_000, batch_size=2)

  assert len(capped.rows) == 5
  assert capped.truncated is False
  assert len(result.fetch_sizes) >= 3