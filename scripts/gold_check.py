import json
import sys
from pathlib import Path

data_dir = Path(sys.argv[1])
gold_path = data_dir / "mini_dev_sqlite_gold.sql"
questions_json = data_dir / "mini_dev_sqlite.json"
questions_jsonl = data_dir / "mini_dev_sqlite.jsonl"
out_path = Path("outputs/gold_as_pred.json")

if not questions_jsonl.exists():
    with open(questions_json) as f:
        questions = json.load(f)
        
    with open(questions_jsonl, "w") as f:
        f.write("\n".join(json.dumps(q) for q in questions) + "\n")
        
    print(f"wrote {questions_jsonl}")

preds = {}
with open(gold_path) as f:
    for line in f:
        if line.strip():
            sql, db_id = line.rstrip("\n").rsplit("\t", 1)
            preds[str(len(preds))] = sql + "\t----- bird -----\t" + db_id

out_path.parent.mkdir(exist_ok=True)
with open(out_path, "w") as f:
    json.dump(preds, f, indent=2)
    
print(f"wrote {len(preds)} gold predictions to {out_path}")
