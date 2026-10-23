"""Bounded context preparation; no inference or semantic-verification claim."""
from __future__ import annotations

import json
from copy import deepcopy

from .evidence_contract import bind_summary, evidence_catalog
from .evidence_retrieval import select_evidence
from .health_projection import sampled_health_summary


def _size(value):
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False))


def coalesce_catalog_metadata(catalog: list[dict], original_reads: list[dict]) -> tuple[list[dict], int]:
    """Keep repeated metadata beside the fetched original and point to it.

    The caller must retain the reads in the same context. Unknown identities,
    different types/values, and existing reference fields are never coalesced.
    Source records and input dictionaries are not modified.
    """
    result = deepcopy(catalog)
    by_id = {read.get('evidence_id'): read for read in original_reads}
    count = 0
    encode = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':'), allow_nan=False)
    for row in result:
        read = by_id.get(row['evidence_id'])
        if not read or type(read.get('index')) is not int or read['index'] != row['index']:
            continue
        original = read.get('evidence', {})
        if ('metadata' not in row or 'metadata' not in original
                or 'metadata_in_original_evidence' in row):
            continue
        if encode(row['metadata']) != encode(original['metadata']):
            continue
        row['metadata_in_original_evidence'] = row['evidence_id']
        del row['metadata']
        count += 1
    return result, count


def prepare_summary_context(source: str, value: dict, items: list[dict], refs: list[dict],
                            question: str = '', limit: int = 8,
                            max_characters: int = 64000) -> dict:
    """Keep summary, typed catalog and optional selected originals together.

    All summary claims and catalog metadata survive or the request fails with a
    paged-read requirement. Only returned original reads may be limited by the
    budget, with explicit IDs/counts; search completeness is never implied.
    """
    if type(max_characters) is not int or not 100 <= max_characters <= 200000:
        raise ValueError('invalid_context_budget')
    if not isinstance(question, str) or len(question) > 2000:
        raise ValueError('invalid_context_question')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('invalid_context_limit')
    catalog = evidence_catalog(items, refs)
    health = source == 'health'
    if health:
        value = sampled_health_summary(items)
    summary = bind_summary(value, items, refs)
    removed = 0
    if health:
        # Remove only a provably exact duplicate, leaving its source identity.
        by_index = {fact['sources'][0]: json.loads(fact['text']) for fact in value['facts']}
        for row in catalog:
            if 'structured_body' in row and row['structured_body'] == by_index.get(row['index']):
                del row['structured_body']
                removed += 1
    result = dict(source=source, summary=summary, source_catalog=catalog,
                  generation_method='deterministic_sampled_health_v1' if health else 'model_generated',
                  deduplicated_statistics_objects=removed, original_selection=None,
                  generated_unverified=True, semantic_support='not_checked', snapshot_only=True)
    if _size(result) > max_characters:
        raise ValueError('context_budget_requires_paged_reads')
    if question.strip():
        # Select before budgeting duplicates; metadata already in the catalog
        # must not by itself prevent an otherwise fitting original body read.
        selection = select_evidence(question, items, refs, limit, 200000)
        result['original_selection'] = selection
        # Selection metadata also takes space. Bound the whole response, rather
        # than just the excerpts. Never drop summary/catalog values to make room.
        while True:
            result['source_catalog'] = catalog
            result.pop('metadata_coalesced_to_originals', None)
            if _size(result) > max_characters:
                compact, count = coalesce_catalog_metadata(catalog, selection['items'])
                result['source_catalog'] = compact
                result['metadata_coalesced_to_originals'] = count
            if _size(result) <= max_characters or not selection['items']:
                break
            omitted = selection['items'].pop()
            selection['over_budget_evidence_ids'].append(omitted['evidence_id'])
            selection['candidate_items_not_returned'] += 1
            selection['selection_state'] = 'budget_limited'
        if _size(result) > max_characters:
            raise ValueError('context_budget_requires_paged_reads')
    return result
