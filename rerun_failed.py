import json
from eval_full import CHECKPOINT_PATH, load_schema_lookup, load_dev_set, get_dev_db_path
from inference import generate_sql_final
from db_runner import compare_execution

def find_failed_indices():
    """
      Records with generated_sql == None are exactly the ones where
      run_full_eval's except branch fired — i.e. genuinely crashed,
      not just scored incorrect. Everything else is trustworthy as-is.
    """
    failed = []
    with open(CHECKPOINT_PATH) as f:
        for line in f:
            r = json.loads(line)
            if r["generated_sql"] is None:
                failed.append(r["index"])
    return failed

def remove_records(indices_to_remove):
    """Rewrites the checkpoint file excluding the given indices, so they can be re-scored fresh."""
    kept = []
    with open(CHECKPOINT_PATH) as f:
        for line in f:
            r = json.loads(line)
            if r["index"] not in indices_to_remove:
                kept.append(r)
    with open(CHECKPOINT_PATH, "w") as f:
        for r in kept:
            f.write(json.dumps(r) + "\n")

def rerun_failed(model, tokenizer, n=5):
    failed_indices = find_failed_indices()
    print(f"Found {len(failed_indices)} failed examples: {failed_indices}")

    if not failed_indices:
        print("Nothing to re-run.")
        return

    remove_records(set(failed_indices))

    schema_lookup = load_schema_lookup()
    dev_set = load_dev_set()

    with open(CHECKPOINT_PATH, "a") as f:
        for i in failed_indices:
            example = dev_set[i]
            db_id = example["db_id"]
            question = example["question"]
            gold_sql = example["query"]

            try:
                db_path = get_dev_db_path(db_id)
                output = generate_sql_final(model, tokenizer, question, db_id, schema_lookup, db_path=db_path, n=n)
                is_correct = compare_execution(db_path, gold_sql, output["sql"])
            except Exception as e:
                output = {"sql": None}
                is_correct = False
                print(f"[{i}] still failing: {e}")

            record = {
                "index": i, "db_id": db_id, "question": question,
                "gold_sql": gold_sql, "generated_sql": output["sql"], "correct": is_correct,
            }
            f.write(json.dumps(record) + "\n")
            f.flush()
            print(f"Re-ran index {i}: correct={is_correct}")