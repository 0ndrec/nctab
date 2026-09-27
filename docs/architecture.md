# Architecture

## Package layout

```
src/nctab/
├── cli.py          # cyclopts entry point; maps NctabError to exit codes
├── app.py          # Textual application
├── config.py       # layered configuration
├── errors.py       # exception hierarchy (exit_code per class)
├── core/           # model, parser, formatter, modal state, file I/O
├── geom/           # arc and transform math
├── ops/            # pure transforms and reports (shift, scale, find, stats, …)
├── check/          # validation rules and diagnostics
├── diff/           # NC-aware normalisation and comparison
├── profiles/       # machine profile loader + built-in *.toml
├── snippets/       # snippet loader + built-in *.toml
├── tui/            # editor widgets and dialogs
└── dnc/            # serial/DNC transfer (optional `dnc` extra, reserved)
```

Dependency direction (lower layers never import higher ones):

```
cli / app / tui
      │
ops · check · diff
      │
core · geom ── profiles
      │
    errors
```

## Design rules

- **Byte-exact round-trip.** A `Line` is a sequence of tokens covering every source
  byte. Lines an operation does not change are written back unchanged.
- **`Decimal`, never `float`.** The exponent of each parsed number is kept, which
  is how *preserve-original* formatting reproduces the source style.
- **Immutable model.** Operations are pure functions
  `apply(program, spec, profile) -> OpResult`; they return a new `Program` and the
  indices of changed lines (used for undo and highlighting).
- **One implementation.** The TUI builds specs and calls the same `ops.*` functions
  as the CLI. No transform logic lives in `tui/` or `app.py`.
- **The parser does not raise.** Suspicious input becomes a `ParseIssue`; modal
  semantics live in `core.state`, validation in `check`.
- **Check rules are isolated.** Each rule is `(ctx) -> Iterable[Diagnostic]`,
  registered in `check.rules.RULES` with a stable `code`. Rules never modify or raise.
- **Safe writes.** `core.io` writes `<file>.tmp` then `os.replace`; the detected
  encoding (UTF-8, UTF-8 BOM, cp1251, latin-1) is preserved.

## Exit codes

Defined in `errors.py`:

| Class | Code |
|---|---|
| `ProgramError` | 1 |
| `ParseError`, `ProfileError` | 2 |
| `NcIOError` | 3 |
