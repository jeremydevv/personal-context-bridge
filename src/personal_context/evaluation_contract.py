"""Deterministic benchmark preflight and accounting, not a semantic grader."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


def validate_cases(cases: list[dict], forbidden_source_clusters=()) -> dict:
    """Reject known rubric/holdout defects before answers are generated.

    Component text must be independently audited against the natural question;
    set equality cannot detect a component that its author forgot to enumerate.
    """
    if not isinstance(cases, list) or not cases:
        raise ValueError('empty_cases')
    forbidden = frozenset(forbidden_source_clusters)
    ids = set()
    field_count = 0
    for case in cases:
        identity = case.get('id')
        if not isinstance(identity, (str, int)) or isinstance(identity, bool):
            raise ValueError('invalid_case_id')
        if identity in ids:
            raise ValueError('duplicate_case')
        ids.add(identity)
        if not isinstance(case.get('question'), str) or not case['question'].strip():
            raise ValueError('missing_question')
        fields = case.get('requested_fields')
        if (not isinstance(fields, list) or not fields
                or any(not isinstance(f, str) or not f.strip() for f in fields)
                or len(set(fields)) != len(fields)):
            raise ValueError('invalid_requested_fields')
        criteria = case.get('criteria', [])
        actual = [c.get('field') for c in criteria]
        if len(actual) != len(fields) or set(actual) != set(fields):
            raise ValueError('criterion_field_mismatch')
        components = case.get('question_components', [])
        if (not components or any(not c.get('component') or not c.get('fields') for c in components)
                or {f for c in components for f in c['fields']} != set(fields)):
            raise ValueError('component_field_mismatch')
        for criterion in criteria:
            anchors = criterion.get('source_ids')
            if not isinstance(anchors, list) or not anchors or any(not isinstance(x, str) or not x for x in anchors):
                raise ValueError('missing_source_anchor')
            if 'expected' not in criterion:
                raise ValueError('missing_expected_value')
            if criterion['expected'] is None and not criterion.get('absence_reason', '').strip():
                raise ValueError('unknown_requires_reason')
        clusters = case.get('source_cluster_ids')
        if not isinstance(clusters, list) or not clusters or any(not isinstance(x, str) or not x for x in clusters):
            raise ValueError('missing_source_cluster')
        if set(clusters) & forbidden:
            raise ValueError('heldout_source_overlap')
        field_count += len(fields)
    return {'valid': True, 'cases': len(cases), 'scored_fields': field_count,
            'semantic_reference_validity': 'requires_independent_audit'}


def numeric_check(value, expected, unit: str | None = None, tolerance=0) -> dict:
    """Compare unambiguous scalar formatting without discarding explicit units.

    Ratios, dates, prose and mixed values require semantic review. Percent values
    remain percent units; 70% is not silently converted to 0.7. No exchange rates
    or month/year conversions are inferred.
    """
    if type(expected) not in (int, float) or type(tolerance) not in (int, float) or tolerance < 0:
        raise ValueError('invalid_numeric_reference')
    try:
        gold, delta = Decimal(str(expected)), Decimal(str(tolerance))
        if not gold.is_finite() or not delta.is_finite():
            raise ValueError('invalid_numeric_reference')
    except InvalidOperation as exc:
        raise ValueError('invalid_numeric_reference') from exc
    explicit_unit = None
    if type(value) in (int, float):
        amount = Decimal(str(value))
    elif isinstance(value, str):
        match = re.fullmatch(r'\s*(\$)?\s*([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(%|/[A-Za-z]+|[A-Za-z]+)?\s*', value)
        if not match:
            return {'status': 'ambiguous_format'}
        amount = Decimal(match[2].replace(',', ''))
        suffix = match[3]
        if match[1]:
            if suffix and not suffix.startswith('/'):
                return {'status': 'ambiguous_format'}
            explicit_unit = 'USD' + (suffix or '')
        elif suffix:
            explicit_unit = 'percent' if suffix == '%' else suffix
    else:
        return {'status': 'ambiguous_format'}
    if not amount.is_finite():
        return {'status': 'ambiguous_format'}
    if explicit_unit and (not unit or explicit_unit.casefold() != unit.casefold()):
        return {'status': 'unit_mismatch'}
    return {'status': 'match' if abs(amount-gold) <= delta else 'mismatch'}


def account_calls(records: list[dict]) -> dict:
    """Count every stage/attempt. Unknown failed-call usage is never zero cost."""
    result = dict(calls=len(records), completed_calls=0, failed_calls=0,
                  calls_missing_usage=0, input_tokens=0, output_tokens=0,
                  total_tokens=0, cached_input_tokens=0)
    for record in records:
        status = record.get('status')
        if status not in ('complete', 'failed'):
            raise ValueError('invalid_call_status')
        result['completed_calls' if status == 'complete' else 'failed_calls'] += 1
        usage = record.get('usage')
        if usage is None:
            if status == 'complete':
                raise ValueError('completed_call_missing_usage')
            result['calls_missing_usage'] += 1
            continue
        keys = ('input_tokens', 'output_tokens', 'total_tokens')
        if any(type(usage.get(k)) is not int or usage[k] < 0 for k in keys):
            raise ValueError('invalid_token_usage')
        if usage['input_tokens'] + usage['output_tokens'] != usage['total_tokens']:
            raise ValueError('inconsistent_token_usage')
        cached = (usage.get('input_tokens_details') or {}).get('cached_tokens', 0)
        if type(cached) is not int or not 0 <= cached <= usage['input_tokens']:
            raise ValueError('invalid_cached_usage')
        for key in keys:
            result[key] += usage[key]
        result['cached_input_tokens'] += cached
    result['cost_complete'] = result['calls_missing_usage'] == 0
    return result
