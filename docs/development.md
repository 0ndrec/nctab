# Development

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.13 is pinned in `.python-version`.

```bash
git clone https://github.com/0ndrec/nctab.git
cd nctab
uv sync --all-extras
uv run nctab --version
```

## Checks

The same commands run in CI on Linux, Windows and macOS:

```bash
uv run ruff check                 # lint
uv run ruff format --check        # formatting (use `ruff format` to fix)
uv run ty check src               # type check
uv run pytest --cov               # tests with coverage
```

Run a subset with `uv run pytest tests/test_ops.py -k shift`.

## Tests

- `tests/golden/*.nc` — reference programs (milling, 5-axis, lathe G71, a broken
  file). Prefer adding a golden file over inlining long programs in tests.
- Property-based tests use [Hypothesis](https://hypothesis.readthedocs.io/).
- TUI tests use Textual's `App.run_test()` pilot (`pytest-asyncio`, auto mode).
- Every new operation needs a round-trip test: untouched lines must be byte-identical.

## Common tasks

**Add a check rule** — write a function in `src/nctab/check/rules.py`, append it to
`RULES` with a new, stable kebab-case `code`, add tests in `tests/test_check.py`.
Never rename an existing code: it is part of the JSON output.

**Add an operation** — create `src/nctab/ops/<name>.py` with a frozen spec dataclass
and a pure function returning `OpResult`; wire it in `cli.py` and, if useful, in the
TUI dialogs. Add tests to `tests/test_ops*.py` and `tests/test_cli_ops.py`.

**Add a profile or snippet** — drop a TOML file into `src/nctab/profiles/` or
`src/nctab/snippets/<profile-id>/`; `tests/test_profiles.py` / `test_snippets.py`
validate all built-ins.

## Dependencies

```bash
uv add <package>            # runtime
uv add --dev <package>      # development
```

Commit `uv.lock` with the change; CI installs with `--locked`.

## Releasing

1. Update `version` in `pyproject.toml` and `__version__` in `src/nctab/__init__.py`.
2. Move the `Unreleased` section of `CHANGELOG.md` under the new version.
3. Commit, then tag and push:

   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```

The `Publish to PyPI` workflow checks that the tag matches the version, runs the
tests, smoke-tests the wheel and sdist, and publishes via trusted publishing.
