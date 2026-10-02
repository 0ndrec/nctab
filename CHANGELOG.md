# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0]

### Added

- Spindle indicator in the editor's inspector: CW / CCW / STOP and the active
  `S` value for the cursor's line.

### Changed

- `M19` (orientation) and `M02` / `M30` (program end) now count as spindle stop
  in the modal state, so `check` no longer treats the spindle as running after
  them.
- CI runs the test suite on Linux, Windows and macOS.

## [0.1.1]

### Added

- Contributor documentation, issue and pull request templates.

### Changed

- Rewrote README; detailed guides moved to `docs/`.

## [0.1.0]

### Added

- TUI editor with outline, file browser, inspector, find & replace, bookmarks,
  snippets and command palette.
- CLI commands: `stats`, `tools`, `check`, `find`, `replace`, `renumber`, `strip`,
  `case`, `shift`, `math`, `feeds`, `scale`, `mirror`, `rotate`, `snippets`, `diff`,
  `profiles`.
- Machine profiles: `fanuc-mill`, `fanuc-turn`, `haas-mill`, `siemens-iso`,
  `generic-iso`.
- Layered configuration and versioned JSON output.

[Unreleased]: https://github.com/0ndrec/nctab/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/0ndrec/nctab/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/0ndrec/nctab/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/0ndrec/nctab/releases/tag/v0.1.0
