"""Rule registry. Each rule module appends to ALL_RULES on import."""

from eqm.rules.base import DataSnapshot, Rule  # noqa: F401

ALL_RULES: list[Rule] = []

_LOADED = False


def ensure_rules_loaded() -> None:
    """Import all rule modules so they register themselves into ALL_RULES."""
    global _LOADED
    if _LOADED:
        return
    from eqm.rules import (  # noqa: F401
        cmdb_linkage,
        entitlement_quality,
        hr_coherence,
        toxic_combinations,
    )
    _LOADED = True


# Auto-load on package import.
ensure_rules_loaded()
