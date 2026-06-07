"""Central read/write for WoodCraft's component attributes.

Every WoodCraft attribute lives under ONE group (config.WC_GROUP) as a plain
name/value string pair on a Component. This module is the only place that touches
that store, so the scheme can grow — new key constants in config.py — without
scattering attribute code across commands.

Design notes:
- Attributes are stamped on the COMPONENT (shared by all its occurrences), so
  classification and per-type data are per-component; physical quantities (counts,
  sizes) are derived per-occurrence by the collector in panels.py.
- Values are always strings on disk; typed helpers (e.g. cost) convert at the edge.
- `Attributes.add` is add-or-update, so set_value is idempotent.
- Functions take a component but work on any entity exposing `.attributes`, which
  keeps the door open for face/edge attributes later without changing this API.
"""

import adsk.core
import adsk.fusion

from .. import config


# ---------------------------------------------------------------------------
# Generic key/value access (the extensible core)
# ---------------------------------------------------------------------------
def set_value(component, name, value) -> bool:
    """Add or replace a WoodCraft attribute on `component`. Returns False if it
    couldn't be written (e.g. a referenced/read-only component)."""
    try:
        component.attributes.add(config.WC_GROUP, name, '' if value is None else str(value))
        return True
    except Exception:
        return False


def get_value(component, name, default=None):
    """Value of a WoodCraft attribute, or `default` if absent/unreadable."""
    try:
        attr = component.attributes.itemByName(config.WC_GROUP, name)
        return attr.value if attr else default
    except Exception:
        return default


def remove_value(component, name) -> bool:
    """Delete a WoodCraft attribute if present. Returns True if one was removed."""
    try:
        attr = component.attributes.itemByName(config.WC_GROUP, name)
        if attr:
            attr.deleteMe()
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------
def get_category(component):
    """'panel' | 'hardware' | None (unclassified)."""
    return get_value(component, config.WC_CATEGORY)


def set_category(component, category) -> bool:
    return set_value(component, config.WC_CATEGORY, category)


def is_panel(component) -> bool:
    return get_category(component) == config.WC_CAT_PANEL


def is_hardware(component) -> bool:
    return get_category(component) == config.WC_CAT_HARDWARE


# ---------------------------------------------------------------------------
# Hardware unit cost
# ---------------------------------------------------------------------------
def get_cost(component, default=0.0) -> float:
    raw = get_value(component, config.WC_COST)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def set_cost(component, cost) -> bool:
    try:
        return set_value(component, config.WC_COST, f'{float(cost):.4f}')
    except (TypeError, ValueError):
        return False
