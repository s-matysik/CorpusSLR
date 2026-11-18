"""Draw Figure 1 (mechanism ablation) from the two ablation CSVs.

The figure used to be drawn interactively, so it could drift from the tables it
illustrates; a regeneration of the tables left a stale picture behind. It is
now a function of `dedup_mechanism_ablation.csv` and
`dedup_ablation_domains.csv`, which `eval_mechanism_ablation.py` writes.

    PYTHONPATH=. python validation/make_fig_ablation.py
"""
from __future__ import annotations

import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DAGGER = "multi-round blocking"


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main():
    gold = {r["mechanism"]: float(r["delta_f1"]) for r in _read("dedup_mechanism_ablation.csv")}
    dom = {r["mechanism"]: float(r["delta_f1"]) for r in _read("dedup_ablation_domains.csv")
           if r["mechanism"] != "shipped defaults"}
    order = sorted(gold, key=lambda m: (dom.get(m, 0.0), gold[m]))
    y = range(len(order))
    h = 0.36

    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    ax.barh([i + h / 2 for i in y], [dom.get(m, 0.0) for m in order], h,
            color="#1f6fb4", label="15 disciplines, live corpora")
    ax.barh([i - h / 2 for i in y], [gold[m] for m in order], h,
            color="#a6cee3", label="ASySD Diabetes gold standard")
    ax.set_yticks(list(y))
    ax.set_yticklabels([m + ("  \u2020" if m == DAGGER else "") for m in order], fontsize=8)
    ax.set_xlabel("F1 lost when the mechanism is switched off", fontsize=9)
    ax.set_title("Which guard matters depends on the corpus", fontsize=9.5, loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=8)
    top = max(list(dom.values()) + list(gold.values()))
    for i, m in enumerate(order):
        for val, dy in ((dom.get(m, 0.0), h / 2), (gold[m], -h / 2)):
            ax.text(val + top * 0.012, i + dy, "%.4f" % val, va="center", fontsize=7)
    ax.set_xlim(0, top * 1.18)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.text(0.99, 0.01, "\u2020 borrowed from ASySD (Hair et al. 2023); the other four "
             "are this work", ha="right", fontsize=7, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    for target in (os.path.join(REPO, "paper", "figures", "fig_ablation.png"),
                   os.path.join(HERE, "fig_ablation.png")):
        fig.savefig(target, dpi=200)
        print("wrote", os.path.relpath(target, REPO))
    plt.close(fig)


if __name__ == "__main__":                                  # pragma: no cover
    main()
