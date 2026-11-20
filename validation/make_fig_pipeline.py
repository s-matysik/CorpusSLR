"""Draw Figure 1: the pipeline and the data quality control at each step.

The figure restates section 2.5 and carries no measured value, so it has no
data file. Each control named here is one the package implements and tests.

    PYTHONPATH=. python validation/make_fig_pipeline.py
"""
from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

STEPS = [
    ("Query", "one SearchQuery,\nsynonym blocks"),
    ("Compile", "one dialect per\ndatabase; warnings\nare kept"),
    ("Collect", "native APIs or\nfile-export\nparsers"),
    ("Deduplicate", "cascade; each merge\nlogged with\nits evidence"),
    ("Report", "PRISMA flow,\nPRISMA-S appendix,\nexports"),
]
CONTROLS = [
    (2, "Completeness", "every record read\nis returned or\nrejected with a reason", "#2c7fb8"),
    (3, "Accuracy", "merge evidence\nlogged; method\nscored on references", "#31a354"),
    (4, "Traceability", "flow arithmetic\nchecked; strategy\nstored; checksum", "#d95f0e"),
]


def main():
    fig, ax = plt.subplots(figsize=(7.4, 3.5))
    ax.set_xlim(-1.5, 101.5)
    ax.set_ylim(0, 50)
    ax.axis("off")
    w, gap = 17.0, 3.75
    xs = [i * (w + gap) for i in range(len(STEPS))]
    for (title, body), x in zip(STEPS, xs):
        ax.add_patch(FancyBboxPatch((x, 30), w, 17, boxstyle="round,pad=0.2,rounding_size=1.2",
                                    fc="#f1f5f9", ec="#475569", lw=1.0))
        ax.text(x + w / 2, 44.3, title, ha="center", va="center", fontsize=9, fontweight="bold")
        ax.text(x + w / 2, 37.2, body, ha="center", va="center", fontsize=7.8, linespacing=1.25)
    for i in range(len(STEPS) - 1):
        ax.annotate("", xy=(xs[i + 1] - 0.2, 38.5), xytext=(xs[i] + w + 0.2, 38.5),
                    arrowprops=dict(arrowstyle="-|>", color="#475569", lw=1.0))
    for idx, name, body, colour in CONTROLS:
        x = xs[idx]
        ax.plot([x + w / 2] * 2, [29.6, 21.5], color=colour, lw=1.2, ls=(0, (3, 2)))
        ax.add_patch(FancyBboxPatch((x, 4), w, 17.2, boxstyle="round,pad=0.2,rounding_size=1.2",
                                    fc="white", ec=colour, lw=1.3))
        ax.text(x + w / 2, 18.0, name, ha="center", va="center", fontsize=9, fontweight="bold",
                color=colour)
        ax.text(x + w / 2, 11.0, body, ha="center", va="center", fontsize=7.6, linespacing=1.25)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    for target in (os.path.join(REPO, "paper", "figures", "fig_pipeline.png"),
                   os.path.join(HERE, "fig_pipeline.png")):
        fig.savefig(target, dpi=220)
        print("wrote", os.path.relpath(target, REPO))
    plt.close(fig)


if __name__ == "__main__":                                   # pragma: no cover
    main()
