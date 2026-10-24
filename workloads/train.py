"""Training job: a small char-level transformer LM on MPS (or CPU), over a real local text file.
Checkpoints every N steps and on pause/stop/device switch; resumes from the last checkpoint.

    uv run python -m workloads.train        # runs under the control file (starts paused)
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import torch
import torch.nn as nn

from .base import CHECKPOINT_DIR, WL, Worker, mps_or_cpu

CFG = WL.get("train", {})
SIDE = CHECKPOINT_DIR / "train.json"   # step count beside the checkpoint, readable without torch


def progress() -> dict:
    return json.loads(SIDE.read_text()) if SIDE.exists() else {"step": 0}


class CharLM(nn.Module):
    def __init__(self, vocab: int, d: int, layers: int, heads: int, seq: int):
        super().__init__()
        self.emb = nn.Embedding(vocab, d)
        self.pos = nn.Parameter(torch.zeros(1, seq, d))
        layer = nn.TransformerEncoderLayer(d, heads, 4 * d, dropout=0.0, batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(layer, layers)
        self.head = nn.Linear(d, vocab)
        self.register_buffer("mask", torch.triu(torch.full((seq, seq), float("-inf")), 1))

    def forward(self, x):
        h = self.emb(x) + self.pos[:, : x.shape[1]]
        return self.head(self.enc(h, mask=self.mask[: x.shape[1], : x.shape[1]], is_causal=True))


class Train(Worker):
    job_id = "train"

    def __init__(self):
        super().__init__()
        text = Path(CFG["corpus"]).read_text(errors="replace")
        self.chars = sorted(set(text))
        self.data = torch.tensor([self.chars.index(c) for c in text[:2_000_000]], dtype=torch.long)
        self.ckpt = CHECKPOINT_DIR / "train.pt"
        self.step_n, self.loss = 0, math.nan
        self.window: list[float] = []

    def load(self, device: str):
        dev = mps_or_cpu(device)
        self.dev = dev
        self.model = CharLM(len(self.chars), CFG["d_model"], CFG["n_layers"], CFG["n_heads"], CFG["seq_len"]).to(dev)
        self.opt = torch.optim.AdamW(self.model.parameters(), lr=CFG["lr"])
        if self.ckpt.exists():
            st = torch.load(self.ckpt, map_location=dev)
            self.model.load_state_dict(st["model"]); self.opt.load_state_dict(st["opt"])
            self.step_n = st["step"]
        self.gen = torch.Generator().manual_seed(self.step_n)

    def checkpoint(self):
        self.ckpt.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ckpt.with_suffix(".tmp")
        torch.save({"model": self.model.state_dict(), "opt": self.opt.state_dict(), "step": self.step_n}, tmp)
        tmp.replace(self.ckpt)
        SIDE.write_text(json.dumps({"step": self.step_n, "t": time.time()}))

    def step(self) -> dict:
        t = time.time()
        seq, bs = CFG["seq_len"], CFG["batch_size"]
        ix = torch.randint(len(self.data) - seq - 1, (bs,), generator=self.gen)
        x = torch.stack([self.data[i:i + seq] for i in ix]).to(self.dev)
        y = torch.stack([self.data[i + 1:i + seq + 1] for i in ix]).to(self.dev)
        loss = nn.functional.cross_entropy(self.model(x).flatten(0, 1), y.flatten())
        self.opt.zero_grad(set_to_none=True); loss.backward(); self.opt.step()
        self.loss = float(loss.item())            # .item() syncs, so the step time is real
        self.step_n += 1
        if self.step_n % CFG["checkpoint_every_steps"] == 0:
            self.checkpoint()
        self.window = (self.window + [time.time() - t])[-20:]
        return {"step": self.step_n, "loss": round(self.loss, 4),
                "rate": round(len(self.window) / sum(self.window), 3), "rate_unit": "steps/s",
                "paused_checkpointed": False}


if __name__ == "__main__":
    Train().run()
