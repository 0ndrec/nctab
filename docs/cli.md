# CLI reference

Run `nctab --help` or `nctab COMMAND --help` for the full list of options.

## Common options

| Option | Applies to | Meaning |
|---|---|---|
| `-p`, `--profile` | all except `profiles` | Machine profile id or path to a profile `.toml` |
| `--json` | all except `profiles` | Machine-readable output (versioned, `schema_version`) |
| `-q`, `--quiet` | all except `profiles` | Suppress informational output |
| `-i`, `--in-place` | transforms | Overwrite the input file |
| `-o`, `--output` | transforms | Write to another path |
| `--dry-run` | transforms | Only show the diff, even with `-i` / `-o` |
| `--backup` | transforms | Keep `FILE.bak` (created once, never overwritten) |
| `-r`, `--range` | transforms | `10-200` (lines), `N100-N500` (blocks), `T12` (one tool) |
| `--digits`, `--rounding` | numeric transforms | Round results instead of keeping source style |

Without `-i` or `-o`, a transform prints a unified diff and changes nothing.

## Inspect

| Command | Description |
|---|---|
| `nctab stats FILE` | Line/block counts, axis ranges, G/M histogram, tools, feeds, speeds, path lengths |
| `nctab tools FILE` | Tool sections: first line, block count, D/H offsets, speeds, feeds, name |
| `nctab check FILE` | 21 validation rules; `--strict` fails on warnings; `--rules` lists codes |
| `nctab profiles` | Available machine profiles, active one marked |

## Search and replace

| Command | Description |
|---|---|
| `nctab find FILE "G41 D"` | Text search; `--regex`, `--case` |
| `nctab find FILE --addr F` | Distinct F values with counts and locations |
| `nctab find FILE --addr F --value 300` | Matching words; `--min` / `--max` for a range |
| `nctab find FILE --code G02` | Every G02 block, regardless of zero padding |
| `nctab replace FILE --addr F --value 300 --to 250` | Replace, keeping the source number style |
| `nctab replace FILE --regex 'X(\d+)\.' --to 'X\1.0'` | Regex replace with back-references |

Comments are never touched unless `--in-comments` is given.

## Transform

| Command | Description |
|---|---|
| `nctab renumber FILE --start 10 --step 10` | Renumber N blocks; `--width 4`, `--strip` |
| `nctab strip FILE --n --comments --blank` | Remove block numbers, comments, blank lines, `/` marks or blocks, spaces |
| `nctab case FILE upper` | Change case of code, not comments |
| `nctab shift FILE --z -0.02` | Translate absolute coordinates |
| `nctab math FILE --addr Z --op add --value -0.013` | Arithmetic on every word of an address |
| `nctab feeds FILE --f-scale 0.9 --f-min 80` | Scale and clamp feeds and spindle speeds |
| `nctab scale FILE --factor 1.02 --about 0,0,0` | Scale linear axes about a point |
| `nctab mirror FILE --axis x` | Mirror an axis, swapping G02/G03 and G41/G42 |
| `nctab rotate FILE --deg 90 --cx 50 --cy 25` | Rotate in G17; multiples of 90° are exact |

## Snippets

```bash
nctab snippets                                   # list
nctab snippets tool-change --set T=7 --set S=4500
```

See [Configuration → Snippets](configuration.md#snippets) for the file format.

## Compare

```bash
nctab diff old.nc new.nc --ignore-n --ignore-whitespace
nctab diff old.nc new.nc --normalize-all --side-by-side
```

Ignore flags: `--ignore-n`, `--ignore-whitespace`, `--ignore-comments`,
`--ignore-zeros`, `--ignore-case`, `--ignore-blank`; `--normalize-all` enables all.

## JSON output

Every reporting command accepts `--json`; each document carries a
`schema_version` field.

```bash
nctab check part.nc --json | jq '.diagnostics[] | select(.severity=="error")'
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Program or operation error; `diff`: files differ |
| `2` | Parse/validation error; `check`: error found (or warning with `--strict`) |
| `3` | I/O error: file system, encoding, serial |
