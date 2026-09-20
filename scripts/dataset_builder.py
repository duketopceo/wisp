#!/usr/bin/env python3
"""dataset_builder.py — build the SFT dataset for the Dim decision router.

Sources:
  1. Real decision logs  (data/decisions.jsonl   — dimd writes {state, jev_answer, outcome})
  2. Correction logs     (data/corrections.jsonl — wrong answers + human fixes)
  3. Synthetic seed      (data/seed/*.jsonl      — schema-valid hand/kimi-labeled examples)

Output: dataset/train.jsonl / val.jsonl / test.jsonl in the Jev /api/alpha/decisions
SFT contract:  {"messages":[{"role":"system",...},{"role":"user","content":<state json>},
                             {"role":"assistant","content":<answer json>}]}

Safety: SCRUBBER runs on every line — redacts api keys, bearer tokens, emails,
home paths, and any value in SCRUB_PATTERNS before anything is written.
"""
import json
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
OUT = REPO / "dataset"

SEED = 42
VAL_FRAC, TEST_FRAC = 0.1, 0.1

SCRUB_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9\-_]{16,}"), "<KEY>"),
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "<KEY>"),
    (re.compile(r"tskey-auth-[A-Za-z0-9\-]+"), "<KEY>"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-_.~+/]{16,}"), "Bearer <TOKEN>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    (re.compile(r"/home/(<user>|kimba)[^\s\"]*"), "<HOME>"),
    (re.compile(r"C:\\Users\\kimba[^\s\"]*"), "<HOME>"),
    (re.compile(r"192\.168\.\d+\.\d+|100\.\d+\.\d+\.\d+"), "<IP>"),
]

SYSTEM = (
    "You are a decision router. Given a state, output a JSON decision. "
    'Output ONLY valid JSON with fields: choice, belief, score. '
    "Set unused fields to null."
)


def scrub(text: str) -> str:
    for pat, repl in SCRUB_PATTERNS:
        text = pat.sub(repl, text)
    return text


def load_examples() -> list[dict]:
    examples: list[dict] = []

    # 1) real decision logs (dimd writes these at runtime)
    for line in (DATA / "decisions.jsonl").read_text().splitlines() if (DATA / "decisions.jsonl").exists() else []:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        state = scrub(json.dumps(rec.get("state", {})))
        ans = rec.get("answer", {})
        answer = {
            "choice": ans.get("choice"),
            "belief": ans.get("belief"),
            "score": ans.get("score"),
        }
        examples.append({"state": state, "answer": answer})

    # 2) corrections — human-fixed answers, weight them twice
    corr_path = DATA / "corrections.jsonl"
    if corr_path.exists():
        for line in corr_path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            state = scrub(json.dumps(rec.get("state", {})))
            fixed = rec.get("correct", {})
            answer = {"choice": fixed.get("choice"), "belief": fixed.get("belief"), "score": fixed.get("score")}
            examples.append({"state": state, "answer": answer})
            examples.append({"state": state, "answer": answer})  # 2x weight

    # 3) synthetic seed files
    for seed in sorted((DATA / "seed").glob("*.jsonl")) if (DATA / "seed").exists() else []:
        for line in seed.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            state = scrub(json.dumps(rec["state"]))
            examples.append({"state": state, "answer": rec["answer"]})

    return examples


def to_sft(ex: dict) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": ex["state"]},
            {"role": "assistant", "content": json.dumps(ex["answer"])},
        ]
    }


def main() -> int:
    examples = load_examples()
    if not examples:
        print("no examples found under data/ — nothing to build", file=sys.stderr)
        return 1

    random.seed(SEED)
    random.shuffle(examples)

    n = len(examples)
    n_val, n_test = int(n * VAL_FRAC), int(n * TEST_FRAC)
    splits = {
        "test": examples[:n_test],
        "val": examples[n_test:n_test + n_val],
        "train": examples[n_test + n_val:],
    }

    OUT.mkdir(exist_ok=True)
    for name, rows in splits.items():
        path = OUT / f"{name}.jsonl"
        with path.open("w") as f:
            for ex in rows:
                f.write(json.dumps(to_sft(ex)) + "\n")
        print(f"{name}: {len(rows)} -> {path}")

    print(f"total: {n} examples | scrubbed with {len(SCRUB_PATTERNS)} patterns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
