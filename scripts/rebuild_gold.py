import json
import sys
import urllib.request
from pathlib import Path

HF_URL = "https://huggingface.co/datasets/birdsql/bird_mini_dev/resolve/main/data/mini_dev_sqlite-00000-of-00001.json"

data_dir = Path(sys.argv[1])
with urllib.request.urlopen(HF_URL) as resp:
    questions = json.load(resp)

with open(data_dir / "mini_dev_sqlite.json", "w") as f:
    json.dump(questions, f, indent=4)

# eval script reads one "<SQL>\t<db_id>" per line
with open(data_dir / "mini_dev_sqlite_gold.sql", "w") as f:
    f.write("".join(f"{q['SQL']}\t{q['db_id']}\n" for q in questions))


(data_dir / "mini_dev_sqlite.jsonl").unlink(missing_ok=True)
print(f"wrote {len(questions)} questions and gold SQL to {data_dir}")
