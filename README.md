<div align="center">

# nctab

**Terminal NC/G-code editor and toolkit for CNC programmers.**

[![CI](https://github.com/0ndrec/nctab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/0ndrec/nctab/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/nctab.svg)](https://pypi.org/project/nctab/)
[![Python](https://img.shields.io/pypi/pyversions/nctab.svg)](https://pypi.org/project/nctab/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/0ndrec/nctab/blob/main/LICENSE)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

[![nctab demo](https://raw.githubusercontent.com/0ndrec/nctab/main/content/thm.png)](https://raw.githubusercontent.com/0ndrec/nctab/main/content/nctab.mp4)

</div>

## Features

- **TUI editor** with a tool-section outline, file browser, live word/modal-state
  inspector, find & replace with preview, bookmarks, snippets and a command palette.
- **Safe by default** — every transform prints a diff and writes nothing unless you
  pass `-i` / `-o`. Writes are atomic; `--backup` keeps a `.bak`.
- **Exact arithmetic** — `Decimal` throughout; untouched lines round-trip byte for byte.
- **Transforms** — renumber, strip, case, shift, scale, mirror, rotate, address math,
  feed/speed scaling, limited to a line, block or tool range.
- **Analysis** — stats, tool list, 21 validation rules, NC-aware diff.
- **Machine profiles** for Fanuc (mill/turn), Haas, Siemens ISO and generic ISO, plus
  your own TOML profiles.
- **CI-friendly** — versioned `--json` output and meaningful exit codes.

## Installation

Requires Python 3.13+.

```bash
uv tool install nctab      # or: pipx install nctab
# one-off, without installing:
uvx nctab --help
```

Optional DNC/serial support: `uv tool install "nctab[dnc]"`.

## Quick start

```bash
nctab part.nc                              # open the editor
nctab stats part.nc                        # summary: axes, codes, tools, feeds
nctab check part.nc --strict               # validate; non-zero exit on problems
nctab shift part.nc --z -0.02              # preview the change as a diff
nctab shift part.nc --z -0.02 -o part_z.nc # write it
nctab diff --ignore-n old.nc new.nc        # compare ignoring block numbers
```

## Documentation

| Guide | Contents |
|---|---|
| [Editor](https://github.com/0ndrec/nctab/blob/main/docs/editor.md) | Layout, key bindings, find & replace |
| [CLI reference](https://github.com/0ndrec/nctab/blob/main/docs/cli.md) | All commands, ranges, JSON output, exit codes |
| [Configuration](https://github.com/0ndrec/nctab/blob/main/docs/configuration.md) | Config layers, machine profiles, snippets |
| [Architecture](https://github.com/0ndrec/nctab/blob/main/docs/architecture.md) | Package layout and design rules |
| [Development](https://github.com/0ndrec/nctab/blob/main/docs/development.md) | Setup, testing, releasing |

## Contributing

Contributions are welcome — please read [CONTRIBUTING.md](https://github.com/0ndrec/nctab/blob/main/CONTRIBUTING.md) and the
[Code of Conduct](https://github.com/0ndrec/nctab/blob/main/CODE_OF_CONDUCT.md). Security issues: see [SECURITY.md](https://github.com/0ndrec/nctab/blob/main/SECURITY.md).
Changes are tracked in [CHANGELOG.md](https://github.com/0ndrec/nctab/blob/main/CHANGELOG.md).

## License

[MIT](https://github.com/0ndrec/nctab/blob/main/LICENSE) © 0ndrec
