"""Program validation (goal.md §6.3)."""

from nctab.check.model import CheckReport, Diagnostic, Severity
from nctab.check.rules import DEFAULT_ARC_TOLERANCE, check_program, rule_codes

__all__ = [
    "DEFAULT_ARC_TOLERANCE",
    "CheckReport",
    "Diagnostic",
    "Severity",
    "check_program",
    "rule_codes",
]
