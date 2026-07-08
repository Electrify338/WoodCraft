"""Global add-on settings for WoodCraft — a tiny key/value JSON store.

Lives next to the stock-sheet library (same folder, see sheets_store.library_dir)
so all WoodCraft user data travels together. Settings are add-on-wide, not
per-design: they tune how reports are computed, not what the model contains.

Current keys:
    waste_percent — % added on top of a panel's raw area when estimating its
        cost from sheet prices in the BOM (nesting never uses 100% of a sheet,
        so a pure area × rate estimate would systematically undershoot).

New settings plug in by adding a key to DEFAULTS; load() overlays the file on
the defaults so older files simply pick up new keys. No Fusion API here — this
module is unit-testable with plain Python.
"""

import json
import os

from . import sheets_store

DEFAULTS = {
    'waste_percent': 10.0,
}


def settings_path():
    """Absolute path to the global settings JSON file."""
    return os.path.join(sheets_store.library_dir(), 'settings.json')


def _num(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize(data):
    """A full settings dict: DEFAULTS overlaid with whatever is usable in `data`."""
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        out['waste_percent'] = max(0.0, _num(data.get('waste_percent'),
                                              DEFAULTS['waste_percent']))
    return out


def load():
    """Settings dict from disk, defaults for anything missing/corrupt. Never
    raises and never writes."""
    try:
        with open(settings_path(), 'r', encoding='utf-8') as f:
            return normalize(json.load(f))
    except Exception:
        return dict(DEFAULTS)


def save(settings):
    """Write (normalized) settings to disk, creating the folder if needed.
    Returns the dict actually written."""
    cleaned = normalize(settings)
    os.makedirs(sheets_store.library_dir(), exist_ok=True)
    with open(settings_path(), 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, indent=2)
    return cleaned


def get_waste_percent():
    """Panel-cost waste factor in percent (e.g. 10.0 → estimates cost 10% more
    area than the panel's raw footprint)."""
    return load()['waste_percent']


def set_waste_percent(value):
    settings = load()
    settings['waste_percent'] = value
    return save(settings)['waste_percent']
