import json
import sqlglot
from sqlglot.expressions import Join, Table, Column, EQ

from eval_full import CHECKPOINT_PATH, get_dev_db_path
from db_runner import execute_queries


def load_results():
    results = []
    with open(CHECKPOINT_PATH) as f:
        for line in f:
            results.append(json.loads(line))
    return results


def is_suspected_spurious_self_join(sql):
    """
      Heuristic: flags a query that joins the same table to itself but
      has no equality condition linking the two aliases together (the
      exact pattern from the Phase 13 incident — JOIN singer AS T2 ON
      T1.country = 'France', which never connects T1 and T2 at all).
      This is a heuristic, not a proof — it can miss variants and
      shouldn't be read as an exact count, only a directional signal.
    """
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return False

    tables = list(parsed.find_all(Table))
    table_names = [t.name.lower() for t in tables]
    aliases = [t.alias or t.name for t in tables]

    # no self-join present at all
    if len(table_names) != len(set(table_names)):
        # a self-join exists (same table name appears more than once) —
        # now check whether any join condition actually equates a column
        # from one alias to a column from another
        has_cross_alias_equality = False
        for join in parsed.find_all(Join):
            on_clause = join.args.get("on")
            if on_clause is None:
                continue
            for eq in on_clause.find_all(EQ):
                cols = list(eq.find_all(Column))
                col_tables = {c.table for c in cols if c.table}
                if len(col_tables) >= 2:
                    has_cross_alias_equality = True
        return not has_cross_alias_equality

    return False


def classify_failure(record):
    db_id = record["db_id"]
    generated_sql = record["generated_sql"]

    if generated_sql is None:
        return "no_valid_query"

    db_path = get_dev_db_path(db_id)
    result = execute_queries(db_path, generated_sql)

    if result is None:
        return "invalid_sql"

    if is_suspected_spurious_self_join(generated_sql):
        return "valid_but_wrong__suspected_spurious_self_join"

    return "valid_but_wrong__other"


def run_analysis():
    results = load_results()
    failures = [r for r in results if not r["correct"]]

    print(f"Total examples: {len(results)}")
    print(f"Total failures: {len(failures)}")

    categories = {}
    for r in failures:
        category = classify_failure(r)
        categories.setdefault(category, []).append(r["index"])

    print("\n--- Failure breakdown ---")
    for category, indices in sorted(categories.items(), key=lambda kv: -len(kv[1])):
        pct_of_failures = 100 * len(indices) / len(failures)
        pct_of_total = 100 * len(indices) / len(results)
        print(f"{category}: {len(indices)} ({pct_of_failures:.1f}% of failures, {pct_of_total:.1f}% of total)")

    return categories