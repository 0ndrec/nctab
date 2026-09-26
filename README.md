# nctab

Terminal NC/G-code editor and toolkit for CNC programmers who work over SSH, in tmux,
on a shop-floor PC without a Windows GUI.

```bash
uvx nctab stats part.nc
uvx nctab shift part.nc --z -0.02 -o part_z.nc
uvx nctab diff --ignore-n old.nc new.nc
```

Nothing is written without `--in-place` / `-i` or `--output` / `-o`: every transform
prints a diff and stops. Writes are atomic, and `--backup` keeps a `.bak` copy.
Numbers are `Decimal` throughout, and a line an operation does not touch comes back
byte for byte.

## Demo

<video src="content/nctab.mp4" controls muted width="100%" playsinline preload="metadata"></video>

If the player does not load, [watch the demo video](content/nctab.mp4).


## Editor

```bash
uvx nctab edit part.nc
uvx nctab part.nc          # the same thing
```

Three panes. On the left a panel with two tabs: the outline of tool sections,
and a file list showing the programs in your G-code folder. The editor is in the
middle, and on the right an inspector decodes the word under the cursor and
shows the modal state in effect on that line. Everything the inspector says
comes from the machine profile, so a custom profile teaches it new codes.

Opening a file from the list is refused while the buffer has unsaved changes:
save with `Ctrl+S`, or press `Ctrl+R` to discard them and open anyway.

The editor is always in insert mode, so no binding is a plain character: typing
`]` inserts `]`.

| Key | Action |
|---|---|
| `Ctrl+F` | Find. Text, pattern, an address word, or a G/M code |
| `F3`, `Shift+F3` | Next and previous match, with a `3/17` counter |
| `Ctrl+G` | Go to a line number, or `N120` for a block |
| `F4`, `Shift+F4` | Next and previous tool change |
| `F5`, `Shift+F5` | Next and previous motion block |
| `Ctrl+B` then a letter | Set a bookmark |
| `Ctrl+J` then a letter | Jump to a bookmark |
| `Ctrl+H` | Find and replace, with a preview of every change |
| `Ctrl+N` | Renumber |
| `Ctrl+T` | Shift, scale, mirror or rotate |
| `F2` | Insert a snippet, with a live preview of the body |
| `F9` | Switch the left panel between the outline and the file list |
| `Ctrl+O` | Focus the left panel |
| `Ctrl+P` | Command palette |
| `Ctrl+S`, `Ctrl+Q` | Save, quit |
| `F1` | Key reminder in the status bar |

### Find and replace

Both keys open the same dialog, in find or replace mode. Pick how to search from
one dropdown: plain text, a regular expression, an address word, or a G or M
code.

The match count updates while you type, and every match is listed with its line
and block number, so an empty search or a pattern that catches too much is
obvious before you commit to it. Picking a row from the list jumps the editor
straight to that match. In the file itself every match is highlighted at once
and the current one picked out, so you can see the distribution at a glance.

In address mode there is no typing at all: one dropdown lists the addresses the
program uses with their counts, the other lists the values that address actually
takes, with the line each first appears on. No more guessing whether the file
says `F300` or `F300.`.

Replace shows what each match becomes before anything is written, computed by
the same code that performs the edit, so the preview cannot disagree with the
result. A match that would not actually change is labelled as such. Individual
rows can be switched off with `Space`, or in bulk with `All` and `None`, so
"every F except that one" needs no cleverness with the pattern.

## Commands

### Inspect

| Command | What it does |
|---|---|
| `nctab stats FILE` | Line and block counts, axis min/max, G/M histogram, tools, feeds, speeds, path lengths |
| `nctab tools FILE` | Each tool section: first line, block count, D/H offsets, speeds, feeds, name from the nearest comment |
| `nctab check FILE` | 21 validation rules; exit code 2 on an error, `--strict` also on a warning |
| `nctab profiles` | Available machine profiles, with the active one marked |

### Search

| Command | What it does |
|---|---|
| `nctab find FILE "G41 D"` | Text search; `--regex` for a pattern, `--case` to match case |
| `nctab find FILE --addr F` | Every distinct F value with counts and where it occurs |
| `nctab find FILE --addr F --value 300` | The F300 words themselves; `--min`/`--max` for a range |
| `nctab find FILE --code G02` | Every G02 block, however it is zero-padded |
| `nctab replace FILE --addr F --value 300 --to 250` | Batch replace keeping the source number style |
| `nctab replace FILE --regex 'X(\d+)\.' --to 'X\1.0'` | Regex replace with back-references |

Comments are never touched unless you pass `--in-comments`.

### Transform

| Command | What it does |
|---|---|
| `nctab renumber FILE --start 10 --step 10` | Renumber N blocks; `--width 4` for `N0010`, `--strip` to remove them |
| `nctab strip FILE --n --comments --blank` | Remove block numbers, comments, blank lines, `/` marks or blocks, spaces |
| `nctab case FILE upper` | Upper- or lower-case the code, leaving comments alone |
| `nctab shift FILE --z -0.02` | Translate absolute coordinates |
| `nctab math FILE --addr Z --op add --value -0.013` | Arithmetic on every word of an address |
| `nctab feeds FILE --f-scale 0.9 --f-min 80` | Scale and clamp feeds and spindle speeds |
| `nctab scale FILE --factor 1.02 --about 0,0,0` | Scale linear axes about a point |
| `nctab mirror FILE --axis x` | Mirror an axis, swapping G02/G03 and G41/G42 |
| `nctab rotate FILE --deg 90 --cx 50 --cy 25` | Rotate in the G17 plane; multiples of 90° are exact |

Every transform takes `--range` / `-r` to limit the work: `10-200` for lines,
`N100-N500` for block numbers, `T12` for one tool's section.

### Snippets

```bash
nctab snippets
nctab snippets tool-change --set T=7 --set S=4500
```

Snippets are TOML files with typed fields and a body. Built-ins cover the
program header and footer, tool change, safe retract and the drilling cycles;
drop your own in `~/.config/nctab/snippets/`, or in a `<profile-id>` folder
under it to limit them to one control. A float field writes `Z-10.` rather than
`Z-10`, because a missing decimal point is read as the least significant
increment on some controls.

### Compare

```bash
nctab diff old.nc new.nc --ignore-n --ignore-whitespace
nctab diff old.nc new.nc --normalize-all --side-by-side
```

Exit code is 1 when the files differ, so it can gate a CI step.

## Machine profiles

`fanuc-mill`, `fanuc-turn`, `haas-mill`, `siemens-iso`, `generic-iso`. A profile
describes the dialect: comment syntax, axis letters, plane codes, the G and M code
dictionary, and the number format. Pick one with `--profile` / `-p`, or point it at
your own file: `-p ./my-control.toml`. User profiles also load from
`~/.config/nctab/profiles/`.

## Configuration

Layers, later ones winning: built-in defaults, `~/.config/nctab/config.toml`, the
nearest `.nctab.toml` at or above the working directory, `NCTAB_*` environment
variables, then CLI flags.

```toml
[editor]
backup = true

[defaults]
directory = "~/nc"    # where the programs live
profile = "fanuc-mill"
digits = "preserve"   # or a number of fractional digits
rounding = "HALF_UP"
arc_tolerance = 0.001
```

`directory` is the folder of G-code programs. The editor's file list opens
there, and a bare file name the CLI cannot find in the working directory is
looked up there too, so `nctab stats OP20.nc` works from anywhere. A file that
does exist where you are standing still wins. Unset means the working
directory, so nothing changes until you set it. `NCTAB_DIR` overrides it for
one command.

A malformed config layer is reported as a warning and skipped, never fatal.

## JSON output

Every reporting command takes `--json` and emits a versioned schema, so `stats`,
`check`, `tools` and `diff` can drive a CI job.

```bash
uvx nctab check part.nc --json | jq '.diagnostics[] | select(.severity=="error")'
```

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check && uv run ruff format --check
uv run ty check src
```

## License

MIT
