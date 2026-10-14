"""Conservative identifiers for deterministic contact correspondence lookup."""

import re


EMAIL = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")


def normalize(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if EMAIL.fullmatch(value):
        return "email:" + value.casefold()
    if value and all(char.isdigit() or char in "+-(). /\u00a0" for char in value):
        digits = "".join(char for char in value if char.isdigit())
        if 7 <= len(digits) <= 15:
            return "phone:" + digits
    return None


def contact_identifiers(payload):
    values = []
    for field in ("emails", "phones"):
        for item in payload.get(field, []):
            if isinstance(item, dict):
                normalized = normalize(item.get("value"))
                if normalized and normalized.startswith("email:" if field == "emails" else "phone:"):
                    values.append(normalized)
    return set(values)


def correspondence_identifiers(kind, payload):
    """Return exact (identifier, role, group_chat) triples."""
    found = set()
    if kind == "mail":
        for field, role in (("senderAddress", "sender"),):
            normalized = normalize(payload.get(field))
            if normalized and normalized.startswith("email:"):
                found.add((normalized, role, False))
        for field in ("to", "cc"):
            for item in payload.get(field, []):
                if isinstance(item, dict):
                    normalized = normalize(item.get("address"))
                    if normalized and normalized.startswith("email:"):
                        found.add((normalized, field, False))
    elif kind == "message":
        sender = normalize(payload.get("sender"))
        if sender and not payload.get("fromMe"):
            found.add((sender, "sender", False))
        for chat in payload.get("chats", []):
            if not isinstance(chat, dict):
                continue
            participants = {normalize(value) for value in chat.get("participants", [])}
            participants.discard(None)
            group = len(participants) > 1
            for identifier in participants:
                found.add((identifier, "participant", group))
    return found
