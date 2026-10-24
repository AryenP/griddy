"""Batch job: sentence embeddings over every line of a real local text file, on GPU (MPS) or
CPU, resumable via items_done (persisted with the embeddings written so far).

    uv run python -m workloads.batch        # runs under the control file (starts paused)
"""
from __future__ import annotations

import glob
import gzip
import json
import time
from pathlib import Path

import numpy as np

from .base import CHECKPOINT_DIR, WL, Worker, mps_or_cpu

CFG = WL.get("batch", {})
STATE = CHECKPOINT_DIR / "batch.json"


def load_items() -> list[str]:
    """Real text from local files, roff macro lines stripped, cut into fixed-size passages.
    Deterministic order so items_done means the same thing across restarts."""
    files = sorted(f for pat in CFG["corpus"] for f in glob.glob(pat) if Path(f).is_file())
    n, words = CFG["words_per_item"], []
    for f in files:
        try:
            raw = Path(f).read_bytes()
            raw = gzip.decompress(raw) if f.endswith(".gz") else raw
        except (OSError, EOFError, gzip.BadGzipFile):
            continue
        for line in raw.decode(errors="replace").splitlines():
            if line.startswith((".", "'", '\\"')):
                continue
            words.extend(line.replace("\\fB", "").replace("\\fR", "").replace("\\fI", "").split())
    return [" ".join(words[i:i + n]) for i in range(0, len(words), n)]


def progress() -> dict:
    """items_done/total without loading the model; computes and caches the total once."""
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    if "total" not in st:
        st = {"items_done": 0, "total": len(load_items())}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st))
    return st


class Batch(Worker):
    job_id = "batch"

    def __init__(self):
        super().__init__()
        self.items = load_items()
        self.state_path = STATE
        self.out_path = CHECKPOINT_DIR / "batch_embeddings.npy"
        st = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.items_done = int(st.get("items_done", 0))
        self.chunks: list[np.ndarray] = []
        self.window: list[tuple[int, float]] = []

    def load(self, device: str):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(CFG["model"], device=mps_or_cpu(device))

    def checkpoint(self):
        if self.chunks:
            prev = np.load(self.out_path) if self.out_path.exists() else np.zeros((0, self.chunks[0].shape[1]), np.float32)
            np.save(self.out_path, np.concatenate([prev] + self.chunks))
            self.chunks = []
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"items_done": self.items_done, "total": len(self.items)}))

    def done(self) -> bool:
        return self.items_done >= len(self.items)

    def step(self) -> dict:
        t = time.time()
        bs = CFG["batch_size"]
        batch = self.items[self.items_done:self.items_done + bs]
        self.chunks.append(self.model.encode(batch, batch_size=bs, convert_to_numpy=True).astype(np.float32))
        self.items_done += len(batch)
        if len(self.chunks) >= 50:
            self.checkpoint()
        self.window = (self.window + [(len(batch), time.time() - t)])[-20:]
        n, dt = sum(a for a, _ in self.window), sum(b for _, b in self.window)
        return {"items_done": self.items_done, "total": len(self.items),
                "fraction": round(self.items_done / len(self.items), 5),
                "rate": round(n / dt, 2), "rate_unit": "items/s", "paused_checkpointed": False}


if __name__ == "__main__":
    Batch().run()
