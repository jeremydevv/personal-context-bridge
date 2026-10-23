"""Snapshot-bound evidence identities; structural checks are not truth judgments.

Indices remain useful for older clients, but never serve as portable identities.
Handles bind the exact original reference and input excerpt, independent of a
retrieved subset's position. No source text is executed or interpreted as policy.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def evidence_catalog(items: list[dict], refs: list[dict]) -> list[dict]:
    """Return lossless typed metadata and handles, without excerpt body text."""
    if len(items) != len(refs):
        raise ValueError('item_reference_length_mismatch')
    rows = []
    for index, (item, ref) in enumerate(zip(items, refs)):
        identity = _canonical({'version': 1, 'reference': ref, 'excerpt': item})
        handle = 'ev1_' + hashlib.sha256(identity.encode('utf-8')).hexdigest()
        row = {k: deepcopy(v) for k, v in item.items()
               if k not in ('text', 'source_index', 'evidence_id')}
        # The Health adapter already computes these statistics deterministically.
        # Preserve that typed result instead of asking prose to reproduce it.
        try:
            body = json.loads(item.get('text') or '')
        except (ValueError, TypeError):
            body = None
        if isinstance(body, dict) and body.get('sampled_statistics_not_deduplicated_totals') is True:
            row['structured_body'] = body
        row.update(index=index, evidence_id=handle, ref=deepcopy(ref))
        rows.append(row)
    return rows


def bind_summary(value: dict, items: list[dict], refs: list[dict]) -> dict:
    """Add handles to existing citations without changing the generated prose."""
    catalog = evidence_catalog(items, refs)
    result = deepcopy(value)
    for field in ('facts', 'actions'):
        for claim in result.get(field, []):
            indices = claim.get('sources')
            if not isinstance(indices, list) or not indices:
                raise ValueError('missing_source_indices')
            if any(type(i) is not int or not 0 <= i < len(catalog) for i in indices):
                raise ValueError('invalid_source_index')
            claim['evidence_ids'] = [catalog[i]['evidence_id'] for i in indices]
    return result


def resolve_evidence(evidence_ids: list[str], items: list[dict], refs: list[dict],
                     max_characters: int = 64000) -> list[dict]:
    """Resolve handles against this snapshot; never reinterpret them as indices.

    Exceeding the caller's budget is explicit. Nothing is silently truncated.
    Returned evidence retains the original index even if just one item is read.
    """
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise ValueError('empty_evidence_request')
    if len(evidence_ids) > 100 or any(not isinstance(x, str) for x in evidence_ids):
        raise ValueError('invalid_evidence_request')
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError('duplicate_evidence_id')
    if type(max_characters) is not int or not 1 <= max_characters <= 200000:
        raise ValueError('invalid_evidence_budget')
    catalog = evidence_catalog(items, refs)
    by_id = {row['evidence_id']: row for row in catalog}
    result = []
    for handle in evidence_ids:
        row = by_id.get(handle)
        if row is None:
            raise ValueError('unknown_evidence_id')
        result.append({'index': row['index'], 'evidence_id': handle,
                       'ref': deepcopy(row['ref']),
                       'evidence': deepcopy(items[row['index']])})
    if len(_canonical(result)) > max_characters:
        raise ValueError('evidence_budget_exceeded')
    return result


def _metadata_literals(value):
    """Yield individual source values, never serialized joins or object keys."""
    if isinstance(value, dict):
        for child in value.values():
            yield from _metadata_literals(child)
    elif isinstance(value, list):
        for child in value:
            yield from _metadata_literals(child)
    else:
        yield value if isinstance(value, str) else _canonical(value)


def check_citations(citations: list[dict], items: list[dict], refs: list[dict]) -> dict:
    """Check identity and literal quotes, explicitly leaving entailment unchecked.

    A quote can be authentic and still fail to support a claim. Callers must not
    convert this result to a factual correctness or semantic-support verdict.
    """
    if not isinstance(citations, list) or len(citations) > 100:
        raise ValueError('invalid_citations')
    catalog = {x['evidence_id']: x for x in evidence_catalog(items, refs)}
    errors = []
    references_valid = bool(citations)
    if not citations:
        errors.append({'position': None, 'code': 'missing_citations'})
    for position, citation in enumerate(citations):
        handle = citation.get('evidence_id') if isinstance(citation, dict) else None
        row = catalog.get(handle) if isinstance(handle, str) else None
        if row is None:
            references_valid = False
            errors.append({'position': position, 'code': 'unknown_evidence_id'})
            continue
        quote = citation.get('quote')
        if not isinstance(quote, str) or not quote.strip():
            errors.append({'position': position, 'code': 'missing_quote'})
            continue
        item = items[row['index']]
        # Check individual original values; never concatenate source fields.
        values = [item.get(key) for key in ('text', 'title', 'at', 'end')]
        values.extend(_metadata_literals(item.get('metadata', {})))
        if not any(isinstance(value, str) and quote in value for value in values):
            errors.append({'position': position, 'code': 'quote_not_in_evidence'})
    return {'references_valid': references_valid,
            'literal_quotes_verified': bool(citations) and not errors,
            'semantic_support': 'not_checked', 'snapshot_only': True,
            'errors': errors}
