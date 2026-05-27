"""Persistent trade journal: the record of every closed trade, so we can tell
whether the bot is actually profitable and whether recent performance is
improving or decaying. The bot itself follows fixed rules — it does not learn;
this history is what lets *us* judge it and tune the parameters with data.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from ..metrics import Metrics, compute
from ..models import Fate, Trade


@dataclass
class JournalEntry:
    ts: float
    symbol: str
    pnl_sol: float
    pnl_r: float
    reason: str
    features: dict | None = None  # token features at entry, for cross-analysis


class TradeJournal:
    def __init__(self, path: str) -> None:
        self.path = path

    def record(self, symbol: str, pnl_sol: float, pnl_r: float,
               reason: str, features: dict | None = None) -> None:
        entry = JournalEntry(time.time(), symbol, pnl_sol, pnl_r, reason, features)
        with open(self.path, "a") as f:
            f.write(json.dumps(entry.__dict__) + "\n")

    def feature_records(self) -> list[dict]:
        """Real closed trades as feature rows, so the same analyzer that studies
        the simulation can study what actually happened live."""
        out = []
        for e in self.load():
            if e.features:
                row = dict(e.features)
                row["pnl_r"] = e.pnl_r
                row["win"] = e.pnl_sol > 0
                out.append(row)
        return out

    def load(self) -> list[JournalEntry]:
        if not os.path.exists(self.path):
            return []
        out: list[JournalEntry] = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(JournalEntry(**json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue  # skip a corrupt line rather than lose the journal
        return out

    @staticmethod
    def _to_trades(entries: list[JournalEntry]) -> list[Trade]:
        return [Trade(symbol=e.symbol, strategy="live", fate=Fate.FLAT,
                      entry_price=0.0, exit_price=0.0, pnl_usd=e.pnl_sol,
                      pnl_r=e.pnl_r, reason=e.reason) for e in entries]

    def summary(self, window: int | None = None) -> Metrics:
        """Metrics over all trades, or just the last `window` of them."""
        entries = self.load()
        if window is not None:
            entries = entries[-window:]
        return compute(self._to_trades(entries))
