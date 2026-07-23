"""Every gene must have meaning (documented, saved in brain.json) and true
value (robust fitness that punishes luck and drawdown; live wiring)."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import fields

from lumuria.evolution import (BOUNDS, GENES, Genome, describe, robust_fitness,
                               save_brain, load_brain)
from lumuria.realtime.decision import DecisionConfig


def test_every_genome_field_has_a_documented_meaning():
    gene_names = {f.name for f in fields(Genome)}
    assert gene_names == set(GENES), "every gene needs a GeneSpec (and vice versa)"
    for name, spec in GENES.items():
        assert len(spec.meaning) > 20, f"{name}: meaning must be a real sentence"
    assert BOUNDS == {k: (s.lo, s.hi, s.is_int) for k, s in GENES.items()}


def test_describe_covers_all_genes_with_readable_values():
    g = Genome(30000, 100, 0.2, 0.3, 0.2, 0.35)
    rows = describe(g)
    assert [r[0] for r in rows] == list(GENES)
    row = dict((name, val) for name, val, _ in rows)
    assert row["min_liquidity"] == "$30,000"
    assert row["min_holders"] == "100"
    assert row["max_top_holder"] == "20%"


def test_brain_json_is_self_explanatory():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    g = Genome(30000, 100, 0.2, 0.3, 0.2, 0.35)
    save_brain(g, path, meta={"fitness": 1.0})
    with open(path) as f:
        data = json.load(f)
    for name in GENES:
        assert data["genes"][name]["value"] == data["genome"][name]
        assert data["genes"][name]["meaning"] == GENES[name].meaning
    assert load_brain(path) == g.clamped()  # roundtrip untouched by the extras
    os.unlink(path)


def test_every_entry_gene_is_wired_into_the_live_decision():
    # A gene the live bot ignores is evolved noise; these must exist live.
    cfg_fields = {f.name for f in fields(DecisionConfig)}
    assert "min_liquidity_usd" in cfg_fields   # <- min_liquidity gene
    assert "min_holders" in cfg_fields         # <- min_holders gene
    assert "max_top_holder_pct" in cfg_fields  # <- max_top_holder gene


def test_true_value_punishes_luck():
    # Same mean profit; the steady genome must be worth more than the lucky one.
    steady = robust_fitness([100.0, 100.0, 100.0], [10.0, 10.0, 10.0])
    lucky = robust_fitness([300.0, 0.0, 0.0], [10.0, 10.0, 10.0])
    assert steady > lucky


def test_true_value_punishes_drawdown():
    calm = robust_fitness([100.0, 100.0], [10.0, 10.0])
    wild = robust_fitness([100.0, 100.0], [400.0, 400.0])
    assert calm > wild
    assert robust_fitness([], []) == 0.0


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failed else 0)
