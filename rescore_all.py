import json
from eval_full import CHECKPOINT_PATH, get_dev_db_path
from db_runner import compare_execution

def rescore_all():
    """
      Re-scores every already-completed example using the fixed,
      column-order-independent compare_execution — no model generation,
      no GPU, just re-running the comparison against SQL that's already
      been generated and saved.
    """
    records = []
    with open(CHECKPOINT_PATH) as f:
        for line in f:
            records.append(json.loads(line))

    flipped = []
    for r in records:
        if r["generated_sql"] is None:
            continue
        db_path = get_dev_db_path(r["db_id"])
        new_correct = compare_execution(db_path, r["gold_sql"], r["generated_sql"])
        if new_correct != r["correct"]:
            flipped.append((r["index"], r["correct"], new_correct))
        r["correct"] = new_correct

    with open(CHECKPOINT_PATH, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    correct = sum(r["correct"] for r in records)
    print(f"Re-scored {len(records)} examples")
    print(f"Flipped: {len(flipped)} (false → true: {sum(1 for _,o,n in flipped if n)}, true → false: {sum(1 for _,o,n in flipped if not n)})")
    print(f"New accuracy: {correct}/{len(records)} = {100*correct/len(records):.2f}%")

if __name__ == "__main__":
    rescore_all()