#!/usr/bin/env python3
"""train_router.py — SFT for the Dim decision router (Qwen3-0.6B).

Usage (on cyberpowa WSL):
  python train_router.py --data dataset/train.jsonl --iters 4700   # full run
  python train_router.py --data dataset/train.jsonl --iters 20     # smoke

Safety:
  - GPU memory ceiling via PYTORCH_CUDA_ALLOC_CONF max_split_size
  - checkpoints every --save-every steps to checkpoints/
  - kill switch:  pkill -f train_router.py
"""
import argparse
import json
import math
import random
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "Qwen/Qwen3-0.6B"


def _to_ids(x):
    """Recursively unwrap whatever apply_chat_template returns into list[int]."""
    if hasattr(x, "ids"):  # tokenizers.Encoding
        return list(x.ids)
    if isinstance(x, dict) and "input_ids" in x:
        return _to_ids(x["input_ids"])
    if isinstance(x, (list, tuple)) and x and not isinstance(x[0], int):
        return _to_ids(x[0])
    return [int(t) for t in x]


class SFTData(Dataset):
    def __init__(self, path, tok, max_len=512):
        self.rows = []
        for line in Path(path).read_text().splitlines():
            rec = json.loads(line)
            template = tok.apply_chat_template(
                rec["messages"], tokenize=False, add_generation_prompt=False
            )
            ids = tok(template, add_special_tokens=False)["input_ids"]
            ids = [int(t) for t in ids][:max_len]
            self.rows.append(ids)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return {"input_ids": self.rows[i]}


def collate(batch, pad_id):
    maxlen = max(len(b["input_ids"]) for b in batch)
    input_ids, labels, mask = [], [], []
    for b in batch:
        ids = b["input_ids"]
        pad = [pad_id] * (maxlen - len(ids))
        input_ids.append(ids + pad)
        labels.append(ids + [-100] * len(pad))  # loss on real tokens only
        mask.append([1] * len(ids) + [0] * len(pad))
    return (
        torch.tensor(input_ids),
        torch.tensor(labels),
        torch.tensor(mask),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset/train.jsonl")
    ap.add_argument("--iters", type=int, default=4700)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--save-every", type=int, default=500)
    ap.add_argument("--out", default="checkpoints")
    args = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, torch_dtype=torch.bfloat16, attn_implementation="sdpa"
    ).cuda()
    model.gradient_checkpointing_enable()
    model.train()

    ds = SFTData(args.data, tok)
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, collate_fn=lambda b: collate(b, tok.pad_token_id or tok.eos_token_id))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.iters)

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    step, running = 0, 0.0
    done = False
    while not done:
        for input_ids, labels, mask in dl:
            input_ids, labels = input_ids.cuda(), labels.cuda()
            loss = model(input_ids=input_ids, labels=labels).loss / args.accum
            loss.backward()
            running += loss.item()
            if (step + 1) % args.accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad()
                step += 1
                if step % 50 == 0:
                    print(f"step {step}/{args.iters} loss {running / (50 * args.accum):.4f}", flush=True)
                    running = 0.0
                if step % args.save_every == 0 or step >= args.iters:
                    model.save_pretrained(out / f"step-{step}")
                    tok.save_pretrained(out / f"step-{step}")
                if step >= args.iters:
                    done = True
                    break
    print("TRAIN-DONE")


if __name__ == "__main__":
    main()
