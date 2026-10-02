"""Validate every movies/*.json: schema, file name, sort order, runtime bounds.
Usage: python3 validate.py   (needs: pip install jsonschema)"""
import json, pathlib, sys
from jsonschema import Draft202012Validator

root = pathlib.Path(__file__).parent
validator = Draft202012Validator(json.loads((root / "schema.json").read_text()))

def secs(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

errors = []
for path in sorted((root / "movies").glob("*.json")):
    doc = json.loads(path.read_text(encoding="utf-8"))
    errs = [f"{path.name}: {e.json_path}: {e.message}" for e in validator.iter_errors(doc)]
    if not errs:
        if path.stem != str(doc["tmdb_id"]):
            errs.append(f"{path.name}: file name must be {doc['tmdb_id']}.json")
        starts = [secs(m["start"]) for m in doc["markers"]]
        if starts != sorted(starts) or len(set(starts)) != len(starts):
            errs.append(f"{path.name}: markers must be sorted by start with no duplicates")
        if starts[-1] >= secs(doc["runtime"]):
            errs.append(f"{path.name}: last marker starts after the runtime")
    errors += errs

print("\n".join(errors) or "all files valid")
sys.exit(1 if errors else 0)
