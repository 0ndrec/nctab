# Contributing to nctab

Thanks for your interest in improving nctab! This document explains how to report
problems and submit changes.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs

Open a [bug report](https://github.com/0ndrec/nctab/issues/new?template=bug_report.yml).
Please include:

- `nctab --version`, OS, and terminal
- the machine profile (`-p`) in use
- a **minimal** NC snippet that reproduces the problem — strip proprietary data
- expected vs. actual output (`--json` output is ideal)

Security vulnerabilities must **not** be reported publicly — see [SECURITY.md](SECURITY.md).

## Suggesting features

Open a [feature request](https://github.com/0ndrec/nctab/issues/new?template=feature_request.yml).
For controls or dialects that are not supported yet, attach sample programs and a
link to the relevant programming manual section if you can.

## Pull requests

1. Fork the repository and create a branch from `main`
   (`fix/arc-tolerance`, `feat/siemens-cycles`, …).
2. Set up the environment — see [docs/development.md](docs/development.md).
3. Make your change, with tests. Bug fixes need a regression test.
4. Make sure all checks pass locally:

   ```bash
   uv run ruff check && uv run ruff format --check
   uv run ty check src
   uv run pytest
   ```

5. Add an entry under **Unreleased** in [CHANGELOG.md](CHANGELOG.md) for
   user-visible changes.
6. Open a PR and fill in the template. Keep PRs focused — one logical change each.

### Code guidelines

- Follow the rules in [docs/architecture.md](docs/architecture.md): pure operations,
  `Decimal` arithmetic, byte-exact round-trip for untouched lines, no transform
  logic in the TUI.
- Line length is 100; formatting is enforced by `ruff format`.
- Public functions have type hints and a docstring.
- Do not change existing check-rule codes or JSON field names — they are a public
  interface. Breaking JSON changes require bumping `schema_version`.

### Commit messages

Use the imperative mood and keep the subject under ~72 characters. Conventional
prefixes are encouraged:

```
fix(check): handle R arcs with negative radius
feat(ops): add --also-incremental to scale
docs: document snippet field formats
```

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
