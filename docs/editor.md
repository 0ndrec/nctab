# Editor

```bash
nctab edit part.nc
nctab part.nc          # the same thing
```

## Layout

```
┌ nctab  OP20.nc  fanuc-mill  LN 412  G90 G17 G41 T12  *modified ┐
├──────────────┬─────────────────────────────────┬───────────────┤
│ Outline/Files│ Editor                          │ Inspector     │
├──────────────┴─────────────────────────────────┴───────────────┤
│ status / diagnostics                                           │
└────────────────────────────────────────────────────────────────┘
```

- **Left panel** — two tabs: the outline of tool sections, and the programs in your
  G-code folder (see `directory` in [Configuration](configuration.md)).
- **Editor** — always in insert mode, so no binding is a plain character.
- **Inspector** — decodes the word under the cursor and shows the modal state in
  effect on that line. Its descriptions come from the active machine profile, so a
  custom profile teaches it new codes.

Opening another file is refused while the buffer has unsaved changes: save with
`Ctrl+S`, or press `Ctrl+R` to discard them and open anyway.

## Key bindings

| Key | Action |
|---|---|
| `Ctrl+F` | Find: text, regex, address word, or G/M code |
| `F3` / `Shift+F3` | Next / previous match |
| `Ctrl+H` | Find and replace with preview |
| `Ctrl+G` | Go to line, or `N120` for a block |
| `F4` / `Shift+F4` | Next / previous tool change |
| `F5` / `Shift+F5` | Next / previous motion block |
| `Ctrl+B` + letter | Set bookmark |
| `Ctrl+J` + letter | Jump to bookmark |
| `Ctrl+N` | Renumber |
| `Ctrl+T` | Shift, scale, mirror or rotate |
| `F2` | Insert snippet |
| `F9` | Toggle outline / file list |
| `Ctrl+O` | Focus left panel |
| `Ctrl+P` | Command palette |
| `Ctrl+S` / `Ctrl+Q` | Save / quit |
| `F1` | Key reminder |

## Find and replace

`Ctrl+F` and `Ctrl+H` open the same dialog. Search modes: plain text, regular
expression, address word, or G/M code.

- The match count and a list of matches (line and block number) update as you type;
  selecting a row jumps to it. All matches are highlighted in the buffer.
- **Address mode** needs no typing: pick an address from the ones the program uses,
  then one of the values it actually takes (`F300` vs `F300.` is visible).
- **Replace** previews every change using the same code that performs the edit.
  Rows can be toggled with `Space`, or in bulk with **All** / **None**.

Transforms invoked from the editor (`Ctrl+N`, `Ctrl+T`, replace) run the same
functions as the CLI, so results are identical.
