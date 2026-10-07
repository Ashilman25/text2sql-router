import json
import sys
from collections import Counter

dev_path, minidev_path, out_path = sys.argv[1:4]
with open(dev_path) as f:
    dev = json.load(f)
    
with open(minidev_path) as f:
    test_ids = {q["question_id"] for q in json.load(f)}

train = [q for q in dev if q["question_id"] not in test_ids]
assert len(dev) - len(train) == len(test_ids), "some Mini-Dev questions are missing from dev.json"

with open(out_path, "w") as f:
    json.dump(train, f, indent=4)
    
print(f"wrote {len(train)} training questions to {out_path}")
print(dict(Counter(q["difficulty"] for q in train)))
