"""Local conversational fact recognizer; evidence suggestions, never write authority.

Rules are explicit and conservative rather than calibrated semantic inference.
No external provider sees messages. Unmarked copying/sarcasm cannot be proven away.
"""
from datetime import date, datetime, timedelta
import hashlib
import re

MONTHS = ('January February March April May June July August September October November December').split()
MONTH_NAMES = {alias.lower(): i for i, name in enumerate(MONTHS, 1)
               for alias in (name, name[:3], 'Sept' if i == 9 else name)}
MONTH = '(?:' + '|'.join(sorted(MONTH_NAMES, key=len, reverse=True)) + r')\.?'
DAY = r'[0-9]{1,2}(?:st|nd|rd|th)?'
DATE = (rf'(?P<value>(?:(?P<month>{MONTH})\s+(?P<day>{DAY})|'
        rf'(?:the\s+)?(?P<day_first>{DAY})\s+(?:of\s+)?(?P<month_second>{MONTH}))'
        r'(?:,?\s+(?P<year>[0-9]{4}))?)(?![\w/])')
STREET = (r"[0-9]{1,6}\s+(?:(?:[NSEW]\.?|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?)\s+){1,6}?"
          r'(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Boulevard|Blvd|Terrace|Ter|Place|Pl)'
          r'(?:\s+(?:Apt|Unit|Suite|#)\s*[A-Za-z0-9-]{1,12})?'
          r'(?:,\s*[A-Za-z]+(?:\s+[A-Za-z]+){0,3},\s*[A-Z]{2}(?:\s+[0-9]{5}(?:-[0-9]{4})?)?)?')
ADDRESS_VALUE = rf'(?P<value>{STREET})(?!\w)'
BIRTH_PREFIX = (r"\b(?:my\s+(?:birthday|bday|b-day)(?:\s+falls\s+on|\s+is(?:\s+coming\s+up)?|['’]s)?"
                r'\s*(?:on\s+)?|I\s+was\s+born\s+(?:on\s+)?)')
BIRTH = re.compile(BIRTH_PREFIX + DATE, re.I)
ADDRESS_RULES = [
    ('home', re.compile(r'\b(?:I\s+(?:live|reside)\s+at|I\s+(?:just\s+)?moved\s+to|my\s+home\s+address\s+is)\s+' + ADDRESS_VALUE, re.I)),
    ('work', re.compile(r'\b(?:my\s+(?:office|workplace)\s+is\s+at|my\s+work\s+address\s+is|I\s+work\s+at)\s+' + ADDRESS_VALUE, re.I)),
    (None, re.compile(r"\b(?:here['’]s\s+my\s+address\s*:|my\s+address\s+is)\s*" + ADDRESS_VALUE, re.I)),
]
# Scope ambiguity blocks the entire message rather than selectively trusting a span.
UNSAFE = re.compile(
    r"[\"“”>]|\b(?:forwarded|fwd|quoted|texted|says?|said|told|wrote|according|if|would|could|might|maybe|perhaps|"
    r"hypothetical|suppose|assuming|imagine|thinks?|believes?|guess|probably|apparently|friend|jok(?:e|ing)|kidding|sarcasm|not\s+sure|tonight|temporar\w*|hotel|"
    r"staying|visiting|for\s+(?:a|one|two|[0-9]+)\s+(?:while|night|day|week|month|year)s?|for\s+now|this\s+week|until|vacation|used\s+to|anymore|no\s+longer|instead|ignore|instructions?|policy|rules?|"
    r"don't|doesn't|didn't|isn't|wasn't|never|not|won't|will\s+move|moving\s+to)\b", re.I)
QUESTION_PATTERNS = [
    ('birthday', None, r"(?:when(?:\s+is|['’]s)\s+your\s+(?:birthday|bday)|what(?:\s+is|['’]s)\s+your\s+(?:birthday|birth\s*date)|when\s+were\s+you\s+born)"),
    ('postal_address', 'home', r'(?:where\s+do\s+you\s+live|what(?:\s+is|[\x27’]s)\s+your\s+home\s+address)'),
    ('postal_address', 'work', r'(?:what(?:\s+is|[\x27’]s)\s+your\s+work\s+address|where\s+is\s+your\s+office)'),
    ('postal_address', None, r'what(?:\s+is|[\x27’]s)\s+your\s+address'),
]


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def safe_payload(p):
    return (isinstance(p, dict) and p.get('contentAvailable') is True
            and p.get('system') is False and p.get('spam') is False
            and p.get('service') in ('iMessage', 'SMS') and not p.get('retractedAt')
            and not p.get('associatedMessageGuid') and p.get('associatedMessageType') in (None, 0)
            and not p.get('attachments') and isinstance(p.get('text'), str)
            and 0 < len(p['text']) <= 8192)


def chat_key(record):
    """Context requires a single stable direct-chat GUID, never just matching names."""
    chats = record['payload'].get('chats', [])
    if (len(chats) == 1 and isinstance(chats[0], dict)
            and isinstance(chats[0].get('guid'), str) and chats[0]['guid']):
        return chats[0]['guid']
    return None


def question_context(record, previous):
    if not previous or not safe_payload(previous['payload']) or previous['payload'].get('fromMe') is not True:
        return None
    if (not chat_key(record) or chat_key(previous) != chat_key(record)
            or previous['payload'].get('replyToGuid')):
        return None
    try:
        gap = instant(record['start']) - instant(previous['start'])
        if not timedelta(0) < gap <= timedelta(hours=24):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    if record['payload'].get('replyToGuid') not in (None, '', previous['payload'].get('guid')):
        return None
    from .identifiers import normalize
    for chat in previous['payload'].get('chats', []):
        participants = {normalize(v) for v in chat.get('participants', [])}
        if participants != {normalize(record['payload'].get('sender'))}:
            return None
    text = previous['payload']['text']
    if UNSAFE.search(text) or re.search(r"(?<!\w)['‘](?=\w)", text):
        return None
    for field, label, pattern in QUESTION_PATTERNS:
        if re.fullmatch(r'(?:hey[,!]?\s+)?' + pattern + r'\s*\?\s*', text, re.I):
            return field, label
    return None


def _fact(record, match, field, label=None, context=None):
    reasons = []
    if field == 'birthday':
        names = match.groupdict()
        month = MONTH_NAMES[(names.get('month') or names['month_second']).rstrip('.').lower()]
        day = int(re.sub(r'\D', '', names.get('day') or names['day_first']))
        value = {'month': month, 'day': day}
        if names.get('year'):
            value['year'] = int(names['year'])
        try:
            birthday = date(value.get('year', 2000), month, day)
            if 'year' in value and birthday > instant(record['start']).date():
                return None
        except (ValueError, KeyError):
            return None
    else:
        value = {'label': label, 'formatted': match['value']}
        if label is None:
            reasons.append('address_label_unspecified')
    result = {'field': field, 'value': value, 'span_start': match.start('value'),
              'span_end': match.end('value'), 'span_hash': hashlib.sha256(match['value'].encode()).hexdigest(),
              'extraction_reasons': reasons, 'extraction_method': 'direct_self_statement'}
    if context:
        result.update(context_record_id=context['id'], context_digest=context['digest'],
                      extraction_method='direct_question_answer')
    return result


def extract(record, previous=None):
    from .identifiers import normalize
    p = record['payload']
    if not safe_payload(p) or p.get('fromMe') is not False or not isinstance(p.get('sender'), str):
        return []
    chats = p.get('chats')
    if not isinstance(chats, list) or not chats:
        return []
    for chat in chats:
        if not isinstance(chat, dict) or not isinstance(chat.get('participants'), list):
            return []
        participants = {normalize(v) for v in chat['participants']}
        if None in participants or len(participants) != 1 or normalize(p['sender']) not in participants:
            return []
    text = p['text']
    if UNSAFE.search(text) or re.search(r"(?<!\w)['‘](?=\w)", text):
        return []
    context_type = question_context(record, previous)
    if p.get('replyToGuid') and not context_type:
        return []
    results = []
    for match in BIRTH.finditer(text):
        # Questions or alternative dates do not constitute affirmative assertions.
        if '?' in re.split(r'[.!\n]', text[match.end():], 1)[0] or re.search(r'\bor\b', text[match.end():], re.I):
            continue
        fact = _fact(record, match, 'birthday')
        if fact:
            results.append(fact)
    for label, rule in ADDRESS_RULES:
        for match in rule.finditer(text):
            if '?' in re.split(r'[.!\n]', text[match.end():], 1)[0] or re.search(r'\bor\b', text[match.end():], re.I):
                continue
            fact = _fact(record, match, 'postal_address', label)
            if fact:
                results.append(fact)
    if not results and context_type:
        field, label = context_type
        pattern = DATE if field == 'birthday' else ADDRESS_VALUE
        # A reply may contain discourse markers and emoji, not another proposition.
        reply = re.compile(r"(?:yeah[,!]?\s+|it's\s+(?:on\s+)?|sure[,!]?\s+)?" + pattern + r'\s*[.!😊🙂🎂🎉]*\s*', re.I)
        match = reply.fullmatch(text)
        if match:
            fact = _fact(record, match, field, label, previous)
            if fact:
                results.append(fact)
    return results
