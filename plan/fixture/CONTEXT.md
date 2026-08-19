# CONTEXT

The only background the solver receives. Static: it does not accumulate
contracts as steps are added (RUNNER_SPEC section 5).

## What is being built

A search engine for Japanese text, up to BM25. This step is the text
normalisation that everything downstream depends on.

## Stack

- Python 3.12, standard library only. Do not add dependencies -- you cannot
  install them, and an import of anything third-party will fail the step.
- Tests are pytest. The project root is on `sys.path`, so a module at
  `src/normalize.py` is imported as `from src.normalize import normalize`.

## Test command

Tests are run by the runner as:

    .venv/bin/pytest -q tests/

You do not need to run it yourself, but if you do, use that exact command.

## Conventions

- Type hints on every public function.
- Docstrings state what the function guarantees, not how it works.
- No `print()` in `src/`.
- Japanese text is data, not encoding trivia: assume UTF-8 throughout and do
  not add encoding shims.

## Domain terms

- **normalisation** -- putting text into one canonical form so that two
  spellings of the same thing compare equal. It happens once on the way in,
  and the same function is applied to queries at search time.
- **full-width / half-width** -- Japanese input produces full-width ASCII
  (`Ａ`, U+FF21) and a full-width space (U+3000) alongside ordinary ASCII.
  Two documents differing only in that are the same document.
