"""Bounded local selection of original excerpts, with no inference calls.

Lexical selection is a fast path, not semantic search or an answer-completeness
guarantee. Missing matches and byte-limited sources remain explicit to callers.
"""
from __future__ import annotations

from datetime import datetime
import json
import re
import unicodedata

from .evidence_contract import evidence_catalog

STOPWORDS = frozenset('a an and are as at be by can did do does for from had has have '
                      'how i in is it me my of on or our show tell that the this to '
                      'was we were what when where which who why with you your'.split())


def _text(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return unicodedata.normalize('NFKC', value).casefold()


def _tokens(value):
    return set(re.findall(r'\w+', _text(value))) - STOPWORDS


def _nearby_same_chat(left, right):
    a, b = left.get('metadata', {}), right.get('metadata', {})
    if not a.get('chats') or a.get('chats') != b.get('chats'):
        return False
    try:
        lo, hi = (datetime.fromisoformat(str(x.get('at')).replace('Z', '+00:00'))
                  for x in (left, right))
        return lo.tzinfo is not None and hi.tzinfo is not None and abs((lo-hi).total_seconds()) <= 300
    except (ValueError, TypeError):
        return False


def select_evidence(query: str, items: list[dict], refs: list[dict],
                    limit: int = 8, max_characters: int = 24000) -> dict:
    """Rank actual excerpt text/metadata; retain exact identities and source types."""
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError('invalid_evidence_query')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('invalid_evidence_limit')
    if type(max_characters) is not int or not 1 <= max_characters <= 200000:
        raise ValueError('invalid_evidence_budget')
    catalog = evidence_catalog(items, refs)
    terms = _tokens(query)
    phrases = [_text(x) for x in re.findall(r'"([^"\n]{2,200})"', query)]
    ranked = []
    for index, item in enumerate(items):
        title, metadata, body = (item.get('title', ''), item.get('metadata', {}), item.get('text', ''))
        score = (4 * len(terms & _tokens(title)) + 3 * len(terms & _tokens(metadata))
                 + len(terms & _tokens(body)))
        all_text = _text(title) + '\n' + _text(metadata) + '\n' + _text(body)
        score += 8 * sum(phrase in all_text for phrase in phrases)
        if score:
            ranked.append((score, index))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    candidates = []
    seen = set()
    for score, index in ranked:
        if index not in seen:
            candidates.append((index, 'lexical_original_match', score))
            seen.add(index)
        if refs[index].get('kind') == 'message':
            for neighbor in (index-1, index+1):
                if (0 <= neighbor < len(items) and neighbor not in seen
                        and refs[neighbor].get('kind') == 'message'
                        and _nearby_same_chat(items[index], items[neighbor])):
                    candidates.append((neighbor, 'same_chat_adjacent_context', 0))
                    seen.add(neighbor)
    selected, over_budget = [], []
    for index, reason, score in candidates:
        if len(selected) >= limit:
            break
        row = {'index': index, 'evidence_id': catalog[index]['evidence_id'],
               'ref': refs[index], 'evidence': items[index],
               'selection_reason': reason, 'selection_score': score}
        size = len(json.dumps(selected+[row], ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        if size > max_characters:
            over_budget.append(row['evidence_id'])
        else:
            selected.append(row)
    state = 'budget_limited' if over_budget else 'matches' if selected else 'no_lexical_match'
    return {'items': selected, 'selection_method': 'local_lexical_originals',
            'selection_state': state, 'inference_calls': 0,
            'coverage_complete': False, 'semantic_retrieval_may_be_needed': True,
            'matched_original_items': len(ranked), 'available_original_items': len(items),
            'candidate_items_not_returned': len(candidates)-len(selected),
            'over_budget_evidence_ids': over_budget,
            'limit': limit, 'max_characters': max_characters, 'snapshot_only': True}
