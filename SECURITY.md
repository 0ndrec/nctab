# Security Policy

## Supported versions

Only the latest release on [PyPI](https://pypi.org/project/nctab/) receives
security fixes.

## Reporting a vulnerability

Please **do not** open a public issue. Report privately via
[GitHub Security Advisories](https://github.com/0ndrec/nctab/security/advisories/new).

Include a description, steps to reproduce, affected version and, if possible, a
proof-of-concept file. You should receive an acknowledgement within 7 days. Once a
fix is released, the advisory will be published with credit to the reporter unless
you prefer to stay anonymous.

## Scope

nctab edits files that are later run on real machine tools. Besides classic issues
(path traversal, unsafe file writes, code execution via config/profile/snippet
files), we treat as security-relevant any bug where a transform **silently** produces
a program that differs from what the preview showed.
