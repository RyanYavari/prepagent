"""Tests for calendar event fetching, normalization and the pre-filter."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services import calendar as cal
from tests.calendar_helpers import NOW, raw_event


def test_normalize_happy_path_truncates_and_keeps_domains_only():
    ev = cal.normalize_event(
        raw_event(
            summary="T" * 500,
            description="<p>Hello&nbsp;<b>world</b></p>" + "x" * 5000,
            attendees=[
                {"email": "me@gmail.com", "self": True, "responseStatus": "accepted"}
            ]
            + [{"email": f"p{i}@acme.com", "displayName": f"P{i}"} for i in range(30)],
        ),
        NOW,
    )
    assert ev is not None
    assert len(ev.title) == cal.TITLE_MAX
    assert len(ev.description) == cal.DESCRIPTION_MAX
    assert "<" not in ev.description
    assert len(ev.attendees) == cal.MAX_ATTENDEES
    assert all(a.domain == "acme.com" for a in ev.attendees)
    assert not hasattr(ev.attendees[0], "email")
    assert ev.user_response == "accepted"
    assert ev.start_date == "2026-11-18"


@pytest.mark.parametrize(
    "over",
    [
        {"status": "cancelled"},
        {"start": {"date": "2026-11-18"}},  # all-day
        {"start": {"dateTime": (NOW - timedelta(days=1)).isoformat()}},  # past
        {"id": None},
        {
            "attendees": [
                {"email": "me@gmail.com", "self": True, "responseStatus": "declined"}
            ]
        },
    ],
)
def test_normalize_skips_events_that_can_never_be_interviews(over):
    assert cal.normalize_event(raw_event(**over), NOW) is None


def test_organizer_self_counts_as_accepted():
    ev = cal.normalize_event(
        raw_event(organizer={"email": "me@gmail.com", "self": True}, attendees=[]), NOW
    )
    assert ev.user_response == "accepted"


def test_unaccepted_invite_is_need_action():
    ev = cal.normalize_event(
        raw_event(
            attendees=[{"email": "jane@acme.com"}, {"email": "me@x.com", "self": True}]
        ),
        NOW,
    )
    assert ev.user_response == "needsAction"


def test_prefilter_keyword_without_attendees_passes():
    ev = cal.normalize_event(raw_event(attendees=[]), NOW)
    assert cal.passes_prefilter(ev)


def test_prefilter_attendees_without_keyword_passes():
    ev = cal.normalize_event(
        raw_event(summary="Sync", description="", attendees=[{"email": "a@b.com"}]),
        NOW,
    )
    assert cal.passes_prefilter(ev)


def test_prefilter_scheduling_platform_passes():
    ev = cal.normalize_event(
        raw_event(
            summary="Meeting",
            description="",
            attendees=[],
            organizer={"email": "noreply@greenhouse.io"},
        ),
        NOW,
    )
    assert cal.passes_prefilter(ev)


def test_prefilter_skips_no_attendee_no_keyword():
    ev = cal.normalize_event(
        raw_event(summary="Focus time", description="", attendees=[]), NOW
    )
    assert not cal.passes_prefilter(ev)


def _patch_http(resp=None, exc=None):
    client = MagicMock()
    client.get = AsyncMock(return_value=resp, side_effect=exc)
    p = patch("services.calendar.httpx.AsyncClient")
    cls = p.start()
    cls.return_value.__aenter__.return_value = client
    return p, client


async def test_fetch_events_requests_primary_window_and_returns_items():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"items": [{"id": "a"}], "nextPageToken": "t"}
    p, client = _patch_http(resp)
    try:
        items, truncated = await cal.fetch_events("tok", NOW, 14)
    finally:
        p.stop()
    assert items == [{"id": "a"}] and truncated is True
    kwargs = client.get.call_args.kwargs
    assert "/calendars/primary/events" in client.get.call_args.args[0]
    assert kwargs["params"]["singleEvents"] == "true"
    assert kwargs["params"]["maxResults"] == cal.MAX_EVENTS
    assert kwargs["headers"]["Authorization"] == "Bearer tok"


async def test_fetch_events_empty_window():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {}
    p, _ = _patch_http(resp)
    try:
        assert await cal.fetch_events("tok", NOW, 14) == ([], False)
    finally:
        p.stop()


async def test_fetch_events_error_is_generic_and_body_logged(caplog):
    resp = MagicMock(status_code=403, text="SECRET-GOOGLE-BODY")
    p, _ = _patch_http(resp)
    try:
        with (
            caplog.at_level("ERROR", logger="services.calendar"),
            pytest.raises(cal.CalendarApiError) as ei,
        ):
            await cal.fetch_events("tok", NOW, 14)
    finally:
        p.stop()
    assert "SECRET-GOOGLE-BODY" not in str(ei.value)
    assert "SECRET-GOOGLE-BODY" in caplog.text


async def test_fetch_events_network_error():
    p, _ = _patch_http(exc=httpx.ConnectError("boom"))
    try:
        with pytest.raises(cal.CalendarApiError):
            await cal.fetch_events("tok", NOW, 14)
    finally:
        p.stop()
