import json
import os
from datasets import load_dataset
from huggingface_hub import hf_hub_download
import wandb

from config import get_wandb_api_key
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
WANDB_RUN_ID_PATH = "/content/drive/MyDrive/text2sql-eval/wandb_run_id.txt"

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

# WANDB Setup

def init_wandb(n, total_examples):
    """
      Resumes the same wandb run across restarts using a run ID saved to
      Drive, rather than starting a new disconnected run each time —
      keeps one continuous history for the whole eval, however many
      times it gets interrupted.
    """
    api_key = get_wandb_api_key()
    if api_key:
        wandb.login(key=api_key)

    run_id = None
    if os.path.exists(WANDB_RUN_ID_PATH):
        with open(WANDB_RUN_ID_PATH) as f:
            run_id = f.read().strip()

    run = wandb.init(
        project="text2sql-eval",
        id=run_id,
        resume="allow",
        config={"n": n, "total_examples": total_examples},
    )

    if run_id is None:
        with open(WANDB_RUN_ID_PATH, "w") as f:
            f.write(run.id)

    return run

# Full Eval run

def run_full_eval(model, tokenizer, n=5, save_every=15, rolling_window=50):
    schema_lookup = load_schema_lookup()
    dev_set = load_dev_set()
    already_done = load_already_done()

    init_wandb(n, len(dev_set))

    print(f"Total examples: {len(dev_set)} | Already done: {len(already_done)}")

    running_correct = already_done and sum(
        1 for i in already_done  # cheap re-derivation isn't tracked here; rolling window resets fresh each session, which is fine — it's a recent-trend signal, not a cumulative one
    ) or 0
    recent_results = []
    total_correct_so_far = 0
    total_scored_so_far = 0

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

            recent_results.append(int(is_correct))
            if len(recent_results) > rolling_window:
                recent_results.pop(0)
            total_scored_so_far += 1
            total_correct_so_far += int(is_correct)

            wandb.log({
                "correct": int(is_correct),
                "rolling_accuracy": sum(recent_results) / len(recent_results),
                "cumulative_accuracy": total_correct_so_far / total_scored_so_far,
                "examples_done": i + 1,
            }, step=i)

            if len(buffer) >= save_every:
                for r in buffer:
                    f.write(json.dumps(r) + "\n")
                f.flush()
                print(f"Checkpointed through index {i} ({i+1}/{len(dev_set)})")
                buffer.clear()

        for r in buffer:
            f.write(json.dumps(r) + "\n")
        f.flush()

    wandb.finish()

def summarize():
    total, correct = 0, 0
    with open(CHECKPOINT_PATH) as f:
        for line in f:
            r = json.loads(line)
            total += 1
            correct += r["correct"]
    accuracy = 100 * correct / total
    print(f"{correct}/{total} = {accuracy:.2f}% execution accuracy")
    return accuracy