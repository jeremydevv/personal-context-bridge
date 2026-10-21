"""Typed MCP change sets. Missing fields are preserved; explicit empty values clear."""
from typing import Literal
from typing_extensions import TypedDict, Required
from pydantic import ConfigDict, with_config


@with_config(ConfigDict(extra='forbid', strict=True))
class Recurrence(TypedDict, total=False):
    frequency: Required[Literal['daily', 'weekly', 'monthly', 'yearly']]
    interval: int
    count: int
    until: str
    weekdays: list[Literal['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']]


@with_config(ConfigDict(extra='forbid', strict=True))
class LocationAlarm(TypedDict):
    title: str
    latitude: float
    longitude: float
    radius: float
    proximity: Literal['arrive', 'leave']


@with_config(ConfigDict(extra='forbid', strict=True))
class RecurrenceEnd(TypedDict):
    date: str
    timezone: str


@with_config(ConfigDict(extra='forbid', strict=True))
class CalendarChanges(TypedDict, total=False):
    title: str
    start_at: str
    end_at: str
    timezone: str
    all_day: bool
    location: str
    notes: str
    url: str
    calendar: str
    alerts: list[int]
    recurrence: Recurrence | None
    recurrence_end: RecurrenceEnd
    availability: Literal['busy', 'free', 'tentative', 'unavailable']


@with_config(ConfigDict(extra='forbid', strict=True))
class ReminderChanges(TypedDict, total=False):
    title: str
    due_at: str
    timezone: str
    notes: str
    url: str
    list_name: str
    alerts: list[int]
    recurrence: Recurrence | None
    priority: Literal[0, 1, 5, 9]
    completed: bool
    location_alarm: LocationAlarm | None


@with_config(ConfigDict(extra='forbid', strict=True))
class Subtask(TypedDict, total=False):
    title: Required[str]
    notes: str


@with_config(ConfigDict(extra='forbid', strict=True))
class Attendee(TypedDict, total=False):
    email: Required[str]
    name: str


@with_config(ConfigDict(extra='forbid', strict=True))
class Attachment(TypedDict):
    filename: str
    media_type: Literal['image/png', 'image/jpeg', 'application/pdf']
    content_base64: str
    sha256: str


@with_config(ConfigDict(extra='forbid', strict=True))
class ImageAttachment(TypedDict):
    filename: str
    media_type: Literal['image/png', 'image/jpeg']
    content_base64: str
    sha256: str


@with_config(ConfigDict(extra='forbid', strict=True))
class TagChanges(TypedDict, total=False):
    set_tags: list[str]
    add_tags: list[str]
    remove_tags: list[str]
