import json
import random

from eval_full import CHECKPOINT_PATH
from analyze_failures import load_results, classify_failure


def sample_uncategorized_failures(n=30, seed=42):
    """
      Pulls a random sample of "valid_but_wrong__other" failures for
      manual review — the same method Phase 3 originally used (review a
      subset, look for recurring patterns by eye, rather than guessing
      at categories automatically). seed is fixed so the sample is
      reproducible if you want to revisit the same examples later.
    """
    results = load_results()
    failures = [r for r in results if not r["correct"]]

    uncategorized = []
    for r in failures:
        category = classify_failure(r)
        if category == "valid_but_wrong__other":
            uncategorized.append(r)

    random.seed(seed)
    sample = random.sample(uncategorized, min(n, len(uncategorized)))

    for r in sample:
        print(f"\n--- index {r['index']} (db: {r['db_id']}) ---")
        print(f"Question: {r['question']}")
        print(f"Gold SQL:      {r['gold_sql']}")
        print(f"Generated SQL: {r['generated_sql']}")

    return sample