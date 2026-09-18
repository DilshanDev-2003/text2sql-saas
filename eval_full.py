import json
from datasets import load_dataset
from huggingface_hub import hf_hub_download

from model_loader import load_model
from inference import generate_sql_final
from db_runner import compare_execution

# Data Loading

def load_schema_lookup():
  schema_data = load_dataset("richardr1126/spider-schema")
  return {row["db_id"]: row for row in schema_data["train"]}

def load_dev_set():
    dev_json_path = hf_hub_download(
        repo_id="dreamerdeo/multispider",
        repo_type="dataset",
        filename="dataset/spider/dev.json",
    )
    with open(dev_json_path) as f:
        return json.load(f) # list of {"db_id", "question", "query", ...} — confirm exact keys once loaded

def get_dev_db_path(db_id):
    return hf_hub_download(
        repo_id="dreamerdeo/multispider",
        repo_type="dataset",
        filename=f"dataset/spider/database/{db_id}/{db_id}.sqlite",
    )

CHECKPOINT_PATH = "/content/drive/MyDrive/text2sql-eval/full_eval_results.jsonl"  # adjust to your actual Drive path

def load_already_done():
    """Returns the set of example indices already scored, so a resume skips them."""
    done = set()
    try:
        with open(CHECKPOINT_PATH) as f:
            for line in f:
                done.add(json.loads(line)["index"])
    except FileNotFoundError:
        pass
    return done

def run_full_eval(model, tokenizer, n=5, save_every=15):
    schema_lookup = load_schema_lookup()
    dev_set = load_dev_set()
    already_done = load_already_done()

    print(f"Total examples: {len(dev_set)} | Already done: {len(already_done)}")

    buffer = []
    with open(CHECKPOINT_PATH, "a") as f:
        for i, example in enumerate(dev_set):
            if i in already_done:
                continue

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
                print(f"[{i}] error: {e}")

            record = {
                "index": i,
                "db_id": db_id,
                "question": question,
                "gold_sql": gold_sql,
                "generated_sql": output["sql"],
                "correct": is_correct,
            }
            buffer.append(record)

            if len(buffer) >= save_every:
                for r in buffer:
                    f.write(json.dumps(r) + "\n")
                f.flush()
                print(f"Checkpointed through index {i} ({i+1}/{len(dev_set)})")
                buffer.clear()

        for r in buffer:
            f.write(json.dumps(r) + "\n")
        f.flush()

def summarize():
    total, correct = 0, 0
    with open(CHECKPOINT_PATH) as f:
        for line in f:
            r = json.loads(line)
            total += 1
            correct += r["correct"]
    print(f"{correct}/{total} = {100*correct/total:.2f}% execution accuracy")    