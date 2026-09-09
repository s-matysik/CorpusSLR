"""Entry point for ``python -m corpusslr``.

Running ``python -m corpusslr.tui`` works but emits a RuntimeWarning, because
``corpusslr/__init__.py`` imports the module before runpy executes it. A
researcher following the README should not have to read a warning about
``sys.modules`` to start their review, so ``python -m corpusslr`` opens the
guided interface directly and the CLI remains available as ``corpusslr <cmd>``.
"""
import sys

from .tui import main


if __name__ == "__main__":               # pragma: no cover
    sys.exit(main(sys.argv[1:]))
