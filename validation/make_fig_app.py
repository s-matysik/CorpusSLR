"""Draw Figure 2: how the browser application reaches the databases.

The figure restates the design of app/ and carries no measured value. The split
between direct and proxied databases is the CORS measurement recorded in
README.md: Web of Science and arXiv send no CORS header to any origin.

    PYTHONPATH=. python validation/make_fig_app.py
"""
from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def box(ax, x, y, w, h, title, body="", fc="#f1f5f9", ec="#475569", tsize=9.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.2,rounding_size=1.0",
                                fc=fc, ec=ec, lw=1.1))
    if body:
        ax.text(x + w / 2, y + h - 3.0, title, ha="center", va="center", fontsize=tsize,
                fontweight="bold")
        ax.text(x + w / 2, y + (h - 6) / 2, body, ha="center", va="center", fontsize=8.2,
                linespacing=1.25)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center", fontsize=tsize - 0.5)


def arrow(ax, a, b, colour="#475569", dashed=False):
    ax.annotate("", xy=b, xytext=a, arrowprops=dict(
        arrowstyle="-|>", color=colour, lw=1.1, ls=(0, (3, 2)) if dashed else "-"))


def main():
    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 54)
    ax.axis("off")
    # the visitor's browser
    ax.add_patch(FancyBboxPatch((0.5, 3), 47, 48, boxstyle="round,pad=0.2,rounding_size=1.5",
                                fc="white", ec="#2c7fb8", lw=1.6))
    ax.text(24, 48.3, "Visitor's browser (static page on GitHub Pages)", ha="center",
            fontsize=8, fontweight="bold", color="#2c7fb8")
    box(ax, 3, 31, 19, 12.5, "Page", "forms, tables,\nPRISMA preview")
    box(ax, 26, 31, 19, 12.5, "Web worker", "keeps the page\nresponsive")
    box(ax, 14.5, 12.5, 21, 14.5, "Pyodide + package", "the unmodified\npackage, served from\nthe same site",
        fc="#e8f1fa", ec="#2c7fb8")
    box(ax, 36.2, 6, 10, 10.5, "Keys", "typed,\nnot stored", fc="#fff7ed", ec="#d95f0e", tsize=8.5)
    arrow(ax, (22, 37), (26, 37))
    arrow(ax, (35.5, 31), (28, 27))
    # databases reached directly
    box(ax, 62, 33, 37, 17, "Direct (CORS header sent)",
        "OpenAlex, Crossref, PubMed,\nSemantic Scholar, Scopus,\nbioRxiv, medRxiv", fc="#ecfdf3", ec="#31a354")
    # proxy and its two databases
    box(ax, 52, 13, 19, 12.5, "Your proxy", "Cloudflare Worker,\nadds the header", fc="#fff7ed", ec="#d95f0e")
    box(ax, 77, 13, 22, 12.5, "Proxied (no header)", "Web of Science,\narXiv", fc="#fff7ed", ec="#d95f0e")
    arrow(ax, (35.5, 19.5), (51.5, 19.5), "#d95f0e")
    arrow(ax, (71.5, 19.5), (76.5, 19.5), "#d95f0e")
    arrow(ax, (47.8, 40), (61.5, 41), "#31a354")
    ax.text(54.5, 46, "HTTPS from\nthe browser", fontsize=7.8, ha="center", color="#31a354")
    ax.text(43.5, 22.2, "HTTPS", fontsize=7.8, ha="center", color="#d95f0e")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    for target in (os.path.join(REPO, "paper", "figures", "fig_app.png"),
                   os.path.join(HERE, "fig_app.png")):
        fig.savefig(target, dpi=220)
        print("wrote", os.path.relpath(target, REPO))
    plt.close(fig)


if __name__ == "__main__":                                   # pragma: no cover
    main()
