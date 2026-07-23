"""Machine profiles: the same bot runs everywhere Lumuria lives — a local
machine, a small/medium/large VPS — with training depth and live cadence
scaled to what the hardware can actually sustain. (The phone is not a compute
profile: it is the Telegram channel every profile reports to.)

`get("auto")` detects the machine (CPU count + RAM) and picks small/medium/
large; "local" is an explicit choice for fast dev feedback, never auto-picked.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    label: str
    # offline training scale (prepare.py / evolve.py)
    tokens: int
    generations: int
    pop_size: int
    # live cadence (live.py): how hard we hit the data APIs
    scan_interval: float   # seconds between new-token scans
    exit_interval: float   # seconds between exit checks on open positions


PROFILES: dict[str, Profile] = {
    "local": Profile("local", "local machine — fast feedback while developing",
                     tokens=1200, generations=8, pop_size=16,
                     scan_interval=30.0, exit_interval=10.0),
    "small": Profile("small", "small VPS (1 vCPU / up to ~2 GB)",
                     tokens=1500, generations=10, pop_size=18,
                     scan_interval=40.0, exit_interval=10.0),
    "medium": Profile("medium", "medium VPS (2 vCPU / ~4 GB)",
                      tokens=2500, generations=15, pop_size=28,
                      scan_interval=25.0, exit_interval=5.0),
    "large": Profile("large", "large VPS (4+ vCPU / 8+ GB)",
                     tokens=4000, generations=20, pop_size=40,
                     scan_interval=15.0, exit_interval=3.0),
}


def _ram_gb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    return math.inf  # unknown (e.g. non-Linux): let CPU count decide alone


def detect(cpus: int | None = None, ram_gb: float | None = None) -> Profile:
    """Pick small/medium/large from the machine's real resources."""
    cpus = cpus if cpus is not None else (os.cpu_count() or 1)
    ram_gb = ram_gb if ram_gb is not None else _ram_gb()
    if cpus >= 4 and ram_gb >= 7:
        return PROFILES["large"]
    if cpus >= 2 and ram_gb >= 3:
        return PROFILES["medium"]
    return PROFILES["small"]


def get(name: str = "auto") -> Profile:
    if name in ("", "auto"):
        return detect()
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown profile {name!r}; pick one of "
                         f"{', '.join(PROFILES)} or 'auto'") from None
