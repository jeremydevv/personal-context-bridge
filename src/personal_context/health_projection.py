"""Lossless presentation of existing sampled statistics, without model aggregation.

This does not validate upstream calculations, deduplicate devices, infer health
conditions, or establish source freshness. Non-statistic records need originals.
"""
from __future__ import annotations

import json


def sampled_health_summary(items: list[dict]) -> dict:
    """Keep each adapter-marked statistics object and exact input index together.

    The source adapter has already calculated these values. Asking a language
    model to select, combine, or retype them risks losing groups and conditions.
    Full structured objects are serialized without rounding or field removal.
    """
    facts = []
    skipped = 0
    for index, item in enumerate(items):
        try:
            value = json.loads(item.get('text') or '')
        except (ValueError, TypeError):
            value = None
        if not isinstance(value, dict) or value.get('sampled_statistics_not_deduplicated_totals') is not True:
            skipped += 1
            continue
        text = json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False)
        facts.append({'text': text, 'sources': [index]})
    limitations = [
        'Sampled statistics are not deduplicated totals; keep date, source, device, category and unit separate.',
        'These are archived adapter calculations, not independently verified measurements or current phone-upload status.',
    ]
    if skipped:
        limitations.append(f'{skipped} non-statistic input records require original evidence reads; no generated claims were substituted for them.')
    return {
        'overview': f'{len(facts)} sampled-statistics groups preserved individually from {len(items)} archived inputs. No cross-record aggregation or clinical interpretation.',
        'facts': facts, 'actions': [], 'topics': ['sampled Health statistics'],
        'uncertainties': limitations,
    }
