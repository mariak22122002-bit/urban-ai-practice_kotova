# AGENTS.md

Python package boilerplate (IDU). Single-package repo; library code lives in `my_package/`, examples in `examples/`, Sphinx docs in `docs/`.

## Setup

- Python >= 3.10 (CI targets exactly 3.10).
- `make venv` then `source .venv/bin/activate`, then one of:
  - `make install-dev` → `pip install -e '.[dev]'` (Jupyter, black, pylint, pre-commit)
  - `make install-test` → **installs extra `test`, which does not exist** (pyproject defines `tests`, plural) — only installs the package; use `pip install -e '.[tests]'` instead.
  - `make install-docs` → `.[docs]` (Sphinx; needs system `pandoc`).
- `package` must be installed (editable is fine) before running anything: `my_package/__init__.py` calls `importlib.metadata.version("my_package")` at import time and raises `PackageNotFoundError` otherwise.

## Commands

- `make format` — isort + black on `my_package/` only (not `tests/`).
- `make lint` — pylint on `my_package/` only.
- `make tests` — pytest. **There is no `test` target** even though CI's `.github/workflows/tests.yml` calls `make test` (it fails there too). Single test: `pytest tests/test_1.py`.
- `make tests-cov` — pytest with coverage.
- `make build` — build wheel/sdist; `make clean` removes build artifacts.

Order when verifying changes: `make format && make lint && make tests`.

## Versioning & release

- Version is dynamic via `setuptools_scm` — derived from git tags, never stored in `pyproject.toml`. Keep full git history (`fetch-depth: 0`) when building.
- Tag `v*` triggers PyPI publish. Pre-release suffixes (`a`/`b`/`rc`/`.dev`) publish only when the tag is on `develop`; final releases only from `main`.
- Docs auto-deploy to GitHub Pages (branch `documentation`) on push to `main`.

## Conventions

- Line length 120 (black, pylint, pycodestyle, isort all configured).
- Docstrings in NumPy style — required for `numpydoc`/Sphinx API docs.
- Pre-commit hook runs black; add it to package + tests style changes.

## Known inconsistencies (do not blindly "fix" without asking)

- README example imports `my_package.my_module_1`; the actual module is `my_module`.
- `pyproject.toml` references license file `LICENCE`, but the file on disk is `LICENSE`.
- Makefile comments for `install-docs` / `install-test` are swapped.
