"""Explicit process-local collector selection; never infer permission to switch."""
from copy import deepcopy

_OPTIONS = {}
_MODES = {'contacts': {'legacy', 'native'}, 'notes': {'legacy', 'database'},
          'mail': {'legacy', 'local', 'imap'}}


def configure_headless(config):
    value = config.get('headless', {})
    if not isinstance(value, dict) or set(value) - set(_MODES):
        raise ValueError('headless must contain only contacts, notes and mail options')
    options = {}
    for source, modes in _MODES.items():
        entry = value.get(source, {'mode': 'legacy'})
        if not isinstance(entry, dict) or entry.get('mode', 'legacy') not in modes:
            raise ValueError('unsupported headless adapter for ' + source)
        options[source] = deepcopy(entry)
        options[source].setdefault('mode', 'legacy')
    _OPTIONS.clear()
    _OPTIONS.update(options)
    return deepcopy(options)


def adapter_options(source):
    return deepcopy(_OPTIONS.get(source, {'mode': 'legacy'}))
