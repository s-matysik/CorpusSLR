# Building the article

How to rebuild `corpusslr_softwarex.pdf` from source, and what is checked
before it is considered rebuilt. This file is build documentation for the
`paper/` directory. It is not part of the submission: the manuscript itself is
`corpusslr_softwarex.tex`, and the Word versions are in `docx/`.

Typographic rule applied to every file here: the only dash is the hyphen `-`.
No en dashes, no em dashes, no LaTeX `--` or `---`. Check 7 and check 8 of
`verify_tex.py` enforce this on the source and on the typeset PDF respectively.

## Files

| File | What it is |
|---|---|
| `corpusslr_softwarex.tex` | The article. `elsarticle`, `final,5p,times,twocolumn`. |
| `references.bib` | Twenty-two references, each confirmed against Crossref or the publisher record in `validation/references_verified.json`. Nothing else is cited. |
| `figures/fig_ablation.png` | Figure 1, copied from `validation/fig_ablation.png`. |
| `figures/fig_domains.png` | Figure 2, copied from `validation/fig_domains.png`. |
| `listing_example.py` | Listing 1, kept runnable. Run it to confirm the code in the article works. |
| `verify_tex.py` | Eight structural checks on the LaTeX source and the PDF, each provable by fault injection. |
| `count_words.py` | Main-text word count against the 3000-word limit. |
| `corpusslr_softwarex.pdf` | The compiled article, 7 pages. |

## Build

The document was compiled in this environment with TeX Live 2025. It builds
with the standard four-step sequence, which is needed because BibTeX runs
between the LaTeX passes and the cross-references settle only on the last one:

```
cd paper
pdflatex corpusslr_softwarex
bibtex   corpusslr_softwarex
pdflatex corpusslr_softwarex
pdflatex corpusslr_softwarex
```

`latexmk -pdf corpusslr_softwarex` does the same in one command.

On this machine TeX Live is installed but not on the default `PATH`. If
`pdflatex` is reported as missing, add it:

```
export PATH="/usr/local/texlive/2025/bin/universal-darwin:$PATH"
```

That is worth checking before concluding that no LaTeX engine is present:
`which pdflatex` can fail while `/usr/local/texlive/2025/bin/*/pdflatex`
exists.

### Required packages

All of these ship with a full TeX Live or MacTeX installation, and all were
resolved here by `kpsewhich`:

`elsarticle.cls`, `elsarticle-num.bst`, `graphicx`, `booktabs`, `amsmath`,
`listings`, `xcolor`, `url`.

With TeX Live's package manager, a minimal installation needs:

```
tlmgr install elsarticle booktabs listings xcolor graphics amsmath url
```

### Where the official template comes from

Elsevier distributes the SoftwareX template as the `elsarticle` bundle:

- CTAN: `https://ctan.org/pkg/elsarticle` (included in TeX Live and MacTeX,
  so a full installation already has it)
- Overleaf: the "Elsevier article (elsarticle)" template, which compiles
  without any local installation
- Elsevier's own author page for the journal, which also carries the Code
  metadata table as a separate form

The Code metadata table in this article follows the C1-C9 field list Elsevier
requires for SoftwareX; the values are read from `LICENSE`, `pyproject.toml`
and `corpusslr/__init__.py` rather than restated.

## Verification

Two things are checked, and they check different failures.

### 1. It compiles

Measured in this environment, from a clean state (no `.aux`, `.bbl`, `.pdf`):

```
pdflatex: exit 0
bibtex  : exit 0, no warnings, 22 entries written to the .bbl
pdflatex: exit 0
pdflatex: exit 0, 7 pages, no errors, no LaTeX warnings,
          no undefined references, 0 overfull boxes
```

### 2. It is structurally sound, checked independently of the compiler

```
python verify_tex.py corpusslr_softwarex.tex
```

Eight checks:

1. `\begin`/`\end` nesting, using a stack rather than a counter, so a crossed
   pair is caught and not merely an unequal count
2. every `\cite` key resolves to an entry in `references.bib`, and uncited
   entries are reported as warnings
3. every `\includegraphics` target exists on disk, honouring `\graphicspath`
4. every `\ref` resolves to a `\label` and every `\label` is referenced,
   orphan labels included
5. every `table` and `figure` environment carries both `\caption` and `\label`
6. every command resolves to the TeX kernel, one of the loaded packages, or a
   definition in the file; the packages and the unresolved commands are listed
7. no en dash, em dash, `--` or `---` in the source
8. no en dash or em dash in the **typeset PDF**

Check 8 exists because check 7 is not sufficient, and that was found by
measurement rather than assumed. BibTeX's `n.dashify` function in
`elsarticle-num.bst` rewrites any literal hyphen in a `pages` field into `--`,
so a `.bib` containing only hyphens still produced en dashes in the reference
list. Brace protection and `\mbox` do not stop it; all four variants were
tested. The hyphen is therefore emitted through a `\pageto` macro defined in
the preamble, which leaves nothing for `n.dashify` to rewrite.

### The checks are proved, not asserted

A check that passes proves nothing until it is shown to fail on a fault of the
same class. `--self-test` injects one fault per check into a copy of the file
and asserts that the right check reports it:

```
python verify_tex.py corpusslr_softwarex.tex --self-test
```

Eleven faults are injected into the source (a deleted `\end`, two crossed
environments, a misspelled `\cite` key, a figure pointing at a missing file, a
`\ref` to a non-existent label, a removed `\caption`, an undefined command,
and five dash variants including one inside a listing), and a twelfth
recompiles the document with an em dash in body text to prove check 8 against
a real PDF. All are caught, each by its own check. If `pdflatex` is absent the
PDF fault is reported as SKIPPED rather than passed, because a check that
cannot run has not passed.

### Word count

```
python count_words.py corpusslr_softwarex.tex
```

Measured: **3000 words** of main text against the 3000-word limit, a margin of
0 words. The article now sits exactly on the limit, so any addition needs a cut
somewhere else. Excluded and reported separately: the frontmatter, all table bodies
(404 words), listings (103 words), captions, the bibliography and the back
matter. The counter was itself fault-tested: adding 100 known words moves the
total by exactly +100, unwrapping a listing raises it, and deleting a sentence
lowers it.

### The code in the article runs

Listing 1 is not transcribed prose. It lives in `listing_example.py` and
executes offline, with no API key and no network:

```
cd ..
PYTHONPATH=. python paper/listing_example.py
```

Measured output, which is what Listing 2 in the article prints:

```
(TITLE-ABS-KEY("deep learning" OR "convolutional neural network"))
AND TITLE-ABS-KEY("diabetic retinopathy")
AND (PUBYEAR > 2019 AND PUBYEAR < 2025) AND (DOCTYPE(ar))
2 identified -> 1 unique
merged by: {'doi': 1}
```

Writing the listing this way caught a defect in the first draft: it used
constructor arguments (`year_from=`, `Corpus.add_source_result`) that do not
exist in the package. Executing it turned an article that would have shipped
uncompilable example code into one whose example is verified. It runs on both
Python 3.13 and Python 3.9.
