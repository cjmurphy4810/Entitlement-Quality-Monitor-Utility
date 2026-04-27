"""Rule registry. Each rule module appends to ALL_RULES on import."""

from eqm.rules.base import DataSnapshot, Rule  # noqa: F401

ALL_RULES: list[Rule] = []
