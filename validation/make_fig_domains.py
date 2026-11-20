"""Draw Figure 2 (fifteen-discipline results) from domains_15_final.csv.

The figure used to be drawn interactively, and its right panel put two
different populations on one axis: the 2,584 pairs that share a DOI (2,489
found, 95 missed) and 154 further merges that are not in that set. Dividing the
second by the first gave a "0.50% error rate" that is not a rate of anything.
The two populations are now drawn as two bars, each against its own total, and
the 154 are described by how they were classified, not by a verdict.

    PYTHONPATH=. python validation/make_fig_domains.py
"""
from __future__ import annotations

import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TRACK = {"nature_hum": "#2c7fb8", "stem": "#31a354", "social": "#d95f0e"}
TRACK_LABEL = {"nature_hum": "nature and humanities", "stem": "STEM",
               "social": "social sciences"}


def _rows():
    with open(os.path.join(HERE, "domains_15_final.csv"), encoding="utf-8",
              newline="") as fh:
        return list(csv.DictReader(fh))


def main():
    rows = sorted(_rows(), key=lambda r: float(r["f1"]))
    n = lambda k: sum(int(float(r[k])) for r in rows)        # noqa: E731
    tp, fn, fp = n("pair_tp"), n("pair_fn"), n("pair_fp")
    judged = tp + fn
    kinds = [("preprint and published version", n("preprint_vs_published")),
             ("two versions on one preprint server", n("two_versions_one_server")),
             ("two preprint servers", n("two_preprint_servers")),
             ("same title, two DOIs", n("same_title_two_dois")),
             ("none of these", n("over_merge"))]
    assert sum(v for _, v in kinds) == fp, (kinds, fp)

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.6, 5.0),
                                 gridspec_kw=dict(width_ratios=[1.25, 1], wspace=0.55))
    y = range(len(rows))
    for i, r in zip(y, rows):
        c = TRACK[r["track"]]
        f1, fx = float(r["f1"]), float(r["f1_excl"])
        ax.plot([f1, fx], [i, i], color="#cccccc", lw=1.4, zorder=1)
        ax.scatter([fx], [i], s=34, facecolor="white", edgecolor=c, lw=1.2, zorder=3)
        ax.scatter([f1], [i], s=20, color=c, zorder=4)     # on top: equal values stay visible
    ax.set_yticks(list(y))
    ax.set_yticklabels([r["domain"].lower() for r in rows], fontsize=7)
    ax.set_xlabel("pairwise F1, identifiers removed", fontsize=8)
    ax.set_title("F1 by discipline", fontsize=9, loc="left")
    ax.tick_params(axis="x", labelsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    h1 = ax.scatter([], [], s=24, color="#666666")
    h2 = ax.scatter([], [], s=30, facecolor="white", edgecolor="#666666", lw=1.2)
    handles = [h1, h2] + [ax.scatter([], [], s=24, color=TRACK[t]) for t in TRACK]
    labels = ["against the DOI reference", "sensitivity: suspected versions not counted"] \
        + [TRACK_LABEL[t] for t in TRACK]
    ax.legend(handles, labels, fontsize=6, frameon=False, loc="upper center",
              bbox_to_anchor=(0.45, -0.14), ncol=2)

    bx.set_title("Merges against the DOI reference", fontsize=9, loc="left")
    groups = [
        ("pairs sharing a DOI\n(n = %s)" % format(judged, ","),
         [("found", tp, "#31a354"), ("missed", fn, "#fdae6b")]),
        ("further merges, both records\ncarry different DOIs (n = %s)" % format(fp, ","),
         [(k, v, c) for (k, v), c in zip(
             kinds, ["#9ecae1", "#6baed6", "#3182bd", "#08519c", "#b2182b"])]),
    ]
    for gi, (name, parts) in enumerate(reversed(groups)):
        total = sum(v for _, v, *_ in parts)
        left = 0.0
        for label, v, c in parts:
            w = 100.0 * v / total
            bx.barh(gi, w, left=left, color=c, height=0.5, edgecolor="white", lw=0.6)
            if w >= 8:
                bx.text(left + w / 2, gi, str(v), ha="center", va="center", fontsize=6.5,
                        color="white" if c not in ("#fdae6b", "#9ecae1") else "black")
            left += w
    bx.set_yticks([0, 1])
    bx.set_yticklabels([g[0] for g in reversed(groups)], fontsize=6.5)
    bx.set_xlim(0, 100)
    bx.set_xlabel("share of the group (%)", fontsize=8)
    bx.tick_params(axis="x", labelsize=7)
    bx.spines[["top", "right"]].set_visible(False)
    hs = [plt.Rectangle((0, 0), 1, 1, color=c) for c in
          ["#31a354", "#fdae6b", "#9ecae1", "#6baed6", "#3182bd", "#08519c", "#b2182b"]]
    ls = ["found (%d)" % tp, "missed (%d)" % fn] + ["%s (%d)" % kv for kv in kinds]
    bx.legend(hs, ls, fontsize=6, frameon=False, loc="upper left",
              bbox_to_anchor=(-0.02, -0.16), ncol=1)
    fig.subplots_adjust(left=0.2, right=0.98, top=0.94, bottom=0.36)
    for target in (os.path.join(REPO, "paper", "figures", "fig_domains.png"),
                   os.path.join(HERE, "fig_domains.png")):
        fig.savefig(target, dpi=200)
        print("wrote", os.path.relpath(target, REPO))
    plt.close(fig)


if __name__ == "__main__":                                  # pragma: no cover
    main()
