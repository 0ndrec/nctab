# Configuration

## Layers

Later layers win:

1. Built-in defaults
2. User config: `~/.config/nctab/config.toml` (platform config dir on Windows/macOS)
3. Nearest `.nctab.toml` at or above the working directory
4. `NCTAB_*` environment variables
5. CLI flags

A malformed layer is reported as a warning and skipped, never fatal.

```toml
[editor]
backup = true
autosave_sec = 0

[defaults]
directory = "~/nc"      # folder with NC programs
profile = "fanuc-mill"
digits = "preserve"     # or a number of fractional digits
rounding = "HALF_UP"    # or HALF_EVEN
arc_tolerance = 0.001
```

`directory` is the editor's file list root. A bare file name the CLI cannot find in
the working directory is also looked up there, so `nctab stats OP20.nc` works from
anywhere; a file in the working directory still wins.

### Environment variables

| Variable | Setting |
|---|---|
| `NCTAB_DIR` | `defaults.directory` |
| `NCTAB_PROFILE` | `defaults.profile` |
| `NCTAB_DIGITS` | `defaults.digits` |
| `NCTAB_ROUNDING` | `defaults.rounding` |
| `NCTAB_BACKUP` | `editor.backup` |
| `NCTAB_AUTOSAVE_SEC` | `editor.autosave_sec` |
| `NCTAB_THEME` | `ui.theme` |
| `NCTAB_KEYBINDINGS` | `ui.keybindings` |

## Machine profiles

Built-in: `fanuc-mill`, `fanuc-turn`, `haas-mill`, `siemens-iso`, `generic-iso`.

A profile describes the control dialect: comment syntax, axis letters, arc format,
plane codes, compensation words, number format, and the G/M code dictionary used by
the inspector and `check`.

```bash
nctab stats part.nc -p haas-mill
nctab stats part.nc -p ./my-control.toml
```

User profiles are loaded from `~/.config/nctab/profiles/*.toml`. Start by copying a
built-in one from [`src/nctab/profiles/`](../src/nctab/profiles/):

```toml
id = "my-mill"
label = "My mill"
comment = [";", "()"]
axes = ["X", "Y", "Z", "A", "C"]
planes = { G17 = "XY", G18 = "ZX", G19 = "YZ" }
units = "mm"
digits = 3

[gcodes]
G00 = "Rapid positioning"

[mcodes]
M06 = "Tool change"
```

Unknown keys are rejected, so typos surface immediately.

## Snippets

Snippets are TOML files with typed fields and a body. Built-ins cover program
header/footer, tool change, safe retract and drilling cycles.

User snippets live in `~/.config/nctab/snippets/`; put them in a `<profile-id>/`
subfolder to limit them to one control.

```toml
# Top-level keys must come before [[fields]].
id = "tool-change"
title = "Tool change"
description = "Retract, change the tool, apply length offset and start the spindle."
body = """
T{T} M06
G43 H{T} Z50.
S{S} M03
"""

[[fields]]
name = "T"
label = "Tool"
type = "int"        # int | float | str | choice
min = 1
max = 99
default = 1
```

Optional field keys: `choices` (for `choice`), `format` (Python format spec, e.g.
`02d` → `T07`). A `float` field always renders a decimal point (`Z-10.`, not
`Z-10`), since some controls read a missing point as the least significant increment.
