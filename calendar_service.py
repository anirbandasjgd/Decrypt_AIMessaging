"""
Smart Office Assistant - Google Calendar Integration
Handles OAuth2 authentication, event creation, availability checking, and meeting invites.
"""
import os
import json
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from config import (
    GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, GOOGLE_SCOPES,
    WORKING_HOURS_START, WORKING_HOURS_END, SLOT_INCREMENT_MINUTES,
    DEFAULT_MEETING_DURATION_MINUTES
)

# Google API imports (graceful if not installed)
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


class CalendarService:
    """Google Calendar service for scheduling and availability management."""

    def __init__(self):
        self.service = None
        self.authenticated = False
        self._error_message = ""

    # ─── Authentication ──────────────────────────────────────────────────
    def is_available(self) -> bool:
        """Check if Google Calendar API libraries are installed."""
        return GOOGLE_API_AVAILABLE

    def has_credentials(self) -> bool:
        """Check if credentials.json exists."""
        return GOOGLE_CREDENTIALS_FILE.exists()

    def is_authenticated(self) -> bool:
        """Check if we have a valid token."""
        return self.authenticated and self.service is not None

    def get_error(self) -> str:
        return self._error_message

    def authenticate(self) -> bool:
        """
        Authenticate with Google Calendar API.
        Uses OAuth2 flow - will open browser on first run.
        Returns True if authentication succeeds.
        """
        if not GOOGLE_API_AVAILABLE:
            self._error_message = (
                "Google API libraries not installed. Run:\n"
                "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            )
            return False

        if not self.has_credentials():
            self._error_message = (
                f"Google credentials file not found at:\n{GOOGLE_CREDENTIALS_FILE}\n\n"
                "To set up Google Calendar integration:\n"
                "1. Go to https://console.cloud.google.com/\n"
                "2. Create a project and enable Google Calendar API\n"
                "3. Create OAuth 2.0 credentials (Desktop application)\n"
                "4. Download credentials.json and place it in the credentials/ folder"
            )
            return False

        try:
            creds = None

            # Check for existing token
            if GOOGLE_TOKEN_FILE.exists():
                creds = Credentials.from_authorized_user_file(
                    str(GOOGLE_TOKEN_FILE), GOOGLE_SCOPES
                )

            # Refresh or create new credentials
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                # Save token for future use
                with open(GOOGLE_TOKEN_FILE, "w") as token:
                    token.write(creds.to_json())

            self.service = build("calendar", "v3", credentials=creds)
            self.authenticated = True
            return True

        except Exception as e:
            self._error_message = f"Authentication failed: {str(e)}"
            return False

    # ─── Event Creation ──────────────────────────────────────────────────
    def create_event(
        self,
        title: str,
        start_datetime: datetime,
        duration_minutes: int = DEFAULT_MEETING_DURATION_MINUTES,
        description: str = "",
        attendee_emails: list[str] = None,
        calendar_id: str = "primary",
        send_notifications: bool = True,
    ) -> dict:
        """
        Create a Google Calendar event with attendees.
        Returns event details including event link.
        """
        if not self.is_authenticated():
            return {"success": False, "error": "Not authenticated with Google Calendar"}

        end_datetime = start_datetime + timedelta(minutes=duration_minutes)

        event_body = {
            "summary": title,
            "description": description,
            "start": {
                "dateTime": start_datetime.isoformat(),
                "timeZone": "Asia/Kolkata",  # IST
            },
            "end": {
                "dateTime": end_datetime.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 60},
                    {"method": "popup", "minutes": 15},
                ],
            },
        }

        if attendee_emails:
            event_body["attendees"] = [{"email": email} for email in attendee_emails]

        # Add Google Meet conferencing
        event_body["conferenceData"] = {
            "createRequest": {
                "requestId": f"meet_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

        try:
            event = self.service.events().insert(
                calendarId=calendar_id,
                body=event_body,
                sendUpdates="all" if send_notifications else "none",
                conferenceDataVersion=1,
            ).execute()

            return {
                "success": True,
                "event_id": event.get("id"),
                "html_link": event.get("htmlLink"),
                "meet_link": event.get("hangoutLink", ""),
                "start": event["start"].get("dateTime"),
                "end": event["end"].get("dateTime"),
                "attendees": [a.get("email") for a in event.get("attendees", [])],
            }

        except HttpError as e:
            return {"success": False, "error": f"Calendar API error: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to create event: {str(e)}"}

    def update_event(
        self,
        event_id: str,
        start_datetime: datetime,
        duration_minutes: int = DEFAULT_MEETING_DURATION_MINUTES,
        calendar_id: str = "primary",
        send_notifications: bool = True,
    ) -> dict:
        """
        Update an existing calendar event's start/end time.
        Sends updates to attendees when send_notifications is True.
        """
        if not self.is_authenticated():
            return {"success": False, "error": "Not authenticated with Google Calendar"}

        end_datetime = start_datetime + timedelta(minutes=duration_minutes)
        body = {
            "start": {
                "dateTime": start_datetime.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "end": {
                "dateTime": end_datetime.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
        }

        try:
            event = self.service.events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
                sendUpdates="all" if send_notifications else "none",
                conferenceDataVersion=1,
            ).execute()

            return {
                "success": True,
                "event_id": event.get("id"),
                "html_link": event.get("htmlLink"),
                "meet_link": event.get("hangoutLink", ""),
                "start": event["start"].get("dateTime"),
                "end": event["end"].get("dateTime"),
            }
        except HttpError as e:
            return {"success": False, "error": f"Calendar API error: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to update event: {str(e)}"}

    def update_event_attendees(
        self,
        event_id: str,
        attendee_emails: list[str],
        calendar_id: str = "primary",
        send_notifications: bool = True,
    ) -> dict:
        """
        Update an event's attendee list. Sends invites to new attendees and updates for existing ones.
        """
        if not self.is_authenticated():
            return {"success": False, "error": "Not authenticated with Google Calendar"}

        body = {"attendees": [{"email": email} for email in attendee_emails]}

        try:
            event = self.service.events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
                sendUpdates="all" if send_notifications else "none",
                conferenceDataVersion=1,
            ).execute()

            return {
                "success": True,
                "event_id": event.get("id"),
                "html_link": event.get("htmlLink"),
                "meet_link": event.get("hangoutLink", ""),
                "attendees": [a.get("email") for a in event.get("attendees", [])],
            }
        except HttpError as e:
            return {"success": False, "error": f"Calendar API error: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to update attendees: {str(e)}"}

    # ─── Availability Checking ───────────────────────────────────────────
    def check_availability(
        self,
        date: datetime,
        duration_minutes: int = DEFAULT_MEETING_DURATION_MINUTES,
        calendar_id: str = "primary",
    ) -> list[dict]:
        """
        Check available time slots on a given date.
        Returns list of available slots within working hours.
        """
        if not self.is_authenticated():
            return []

        # Define the time range (working hours)
        day_start = date.replace(
            hour=WORKING_HOURS_START, minute=0, second=0, microsecond=0
        )
        day_end = date.replace(
            hour=WORKING_HOURS_END, minute=0, second=0, microsecond=0
        )

        try:
            # Get busy times using freebusy API
            body = {
                "timeMin": day_start.isoformat() + "+05:30",
                "timeMax": day_end.isoformat() + "+05:30",
                "timeZone": "Asia/Kolkata",
                "items": [{"id": calendar_id}],
            }

            result = self.service.freebusy().query(body=body).execute()
            busy_times = result.get("calendars", {}).get(calendar_id, {}).get("busy", [])

            # Parse busy periods
            busy_periods = []
            for busy in busy_times:
                start = datetime.fromisoformat(busy["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(busy["end"].replace("Z", "+00:00"))
                busy_periods.append((start, end))

            # Find available slots
            available_slots = []
            current_time = day_start
            while current_time + timedelta(minutes=duration_minutes) <= day_end:
                slot_end = current_time + timedelta(minutes=duration_minutes)

                # Check if slot overlaps with any busy period
                is_available = True
                for busy_start, busy_end in busy_periods:
                    # Convert to naive for comparison
                    bs = busy_start.replace(tzinfo=None)
                    be = busy_end.replace(tzinfo=None)
                    if current_time < be and slot_end > bs:
                        is_available = False
                        break

                if is_available:
                    available_slots.append({
                        "start": current_time.strftime("%H:%M"),
                        "end": slot_end.strftime("%H:%M"),
                        "start_datetime": current_time,
                    })

                current_time += timedelta(minutes=SLOT_INCREMENT_MINUTES)

            return available_slots

        except Exception as e:
            print(f"Error checking availability: {e}")
            return []

    def find_first_available_slot(
        self,
        target_date: datetime,
        duration_minutes: int = DEFAULT_MEETING_DURATION_MINUTES,
        calendar_id: str = "primary",
    ) -> Optional[dict]:
        """Find the first available time slot on a given date."""
        slots = self.check_availability(target_date, duration_minutes, calendar_id)
        return slots[0] if slots else None

    # ─── Event Queries ───────────────────────────────────────────────────
    def get_upcoming_events(self, max_results: int = 10, calendar_id: str = "primary") -> list[dict]:
        """Get upcoming events."""
        if not self.is_authenticated():
            return []

        try:
            now = datetime.utcnow().isoformat() + "Z"
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = events_result.get("items", [])
            return [
                {
                    "id": e.get("id"),
                    "title": e.get("summary", "No Title"),
                    "start": e["start"].get("dateTime", e["start"].get("date")),
                    "end": e["end"].get("dateTime", e["end"].get("date")),
                    "attendees": [a.get("email") for a in e.get("attendees", [])],
                    "link": e.get("htmlLink", ""),
                }
                for e in events
            ]
        except Exception as e:
            print(f"Error fetching events: {e}")
            return []

    def get_events_on_date(self, date: datetime, calendar_id: str = "primary") -> list[dict]:
        """Get all events on a specific date."""
        if not self.is_authenticated():
            return []

        try:
            day_start = date.replace(hour=0, minute=0, second=0).isoformat() + "+05:30"
            day_end = date.replace(hour=23, minute=59, second=59).isoformat() + "+05:30"

            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=day_start,
                timeMax=day_end,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = events_result.get("items", [])
            return [
                {
                    "id": e.get("id"),
                    "title": e.get("summary", "No Title"),
                    "start": e["start"].get("dateTime", e["start"].get("date")),
                    "end": e["end"].get("dateTime", e["end"].get("date")),
                    "attendees": [a.get("email") for a in e.get("attendees", [])],
                }
                for e in events
            ]
        except Exception as e:
            print(f"Error fetching events: {e}")
            return []


class MockCalendarService(CalendarService):
    """
    Mock calendar service for testing without Google API credentials.
    Simulates calendar operations with local data.
    """

    def __init__(self):
        super().__init__()
        self.events = []
        self.authenticated = True
        self._mock_busy_times = []

    def is_available(self) -> bool:
        return True

    def has_credentials(self) -> bool:
        return True

    def is_authenticated(self) -> bool:
        return True

    def authenticate(self) -> bool:
        self.authenticated = True
        return True

    def create_event(self, title, start_datetime, duration_minutes=45,
                     description="", attendee_emails=None, calendar_id="primary",
                     send_notifications=True) -> dict:
        import uuid
        event_id = f"mock_{uuid.uuid4().hex[:10]}"
        end_datetime = start_datetime + timedelta(minutes=duration_minutes)

        event = {
            "id": event_id,
            "title": title,
            "start": start_datetime.isoformat(),
            "end": end_datetime.isoformat(),
            "description": description,
            "attendees": attendee_emails or [],
        }
        self.events.append(event)

        return {
            "success": True,
            "event_id": event_id,
            "html_link": f"https://calendar.google.com/event?eid={event_id}",
            "meet_link": f"https://meet.google.com/mock-{event_id[:8]}",
            "start": start_datetime.isoformat(),
            "end": end_datetime.isoformat(),
            "attendees": attendee_emails or [],
        }

    def update_event(self, event_id: str, start_datetime: datetime,
                    duration_minutes=45, calendar_id="primary",
                    send_notifications=True) -> dict:
        end_datetime = start_datetime + timedelta(minutes=duration_minutes)
        for event in self.events:
            if event.get("id") == event_id:
                event["start"] = start_datetime.isoformat()
                event["end"] = end_datetime.isoformat()
                return {
                    "success": True,
                    "event_id": event_id,
                    "html_link": event.get("html_link", f"https://calendar.google.com/event?eid={event_id}"),
                    "meet_link": event.get("meet_link", f"https://meet.google.com/mock-{event_id[:8]}"),
                    "start": start_datetime.isoformat(),
                    "end": end_datetime.isoformat(),
                }
        return {"success": False, "error": "Event not found"}

    def update_event_attendees(self, event_id: str, attendee_emails: list,
                               calendar_id="primary", send_notifications=True) -> dict:
        for event in self.events:
            if event.get("id") == event_id:
                event["attendees"] = list(attendee_emails) if attendee_emails else []
                return {
                    "success": True,
                    "event_id": event_id,
                    "html_link": event.get("html_link", f"https://calendar.google.com/event?eid={event_id}"),
                    "meet_link": event.get("meet_link", f"https://meet.google.com/mock-{event_id[:8]}"),
                    "attendees": event["attendees"],
                }
        return {"success": False, "error": "Event not found"}

    def check_availability(self, date, duration_minutes=45, calendar_id="primary") -> list[dict]:
        day_start = date.replace(hour=WORKING_HOURS_START, minute=0, second=0)
        day_end = date.replace(hour=WORKING_HOURS_END, minute=0, second=0)

        # Generate available slots (simulate some busy times)
        available_slots = []
        current_time = day_start
        while current_time + timedelta(minutes=duration_minutes) <= day_end:
            slot_end = current_time + timedelta(minutes=duration_minutes)

            # Check against stored events
            is_available = True
            for event in self.events:
                ev_start = datetime.fromisoformat(event["start"])
                ev_end = datetime.fromisoformat(event["end"])
                if current_time < ev_end and slot_end > ev_start:
                    is_available = False
                    break

            if is_available:
                available_slots.append({
                    "start": current_time.strftime("%H:%M"),
                    "end": slot_end.strftime("%H:%M"),
                    "start_datetime": current_time,
                })

            current_time += timedelta(minutes=SLOT_INCREMENT_MINUTES)

        return available_slots

    def find_first_available_slot(self, target_date, duration_minutes=45,
                                  calendar_id="primary") -> Optional[dict]:
        slots = self.check_availability(target_date, duration_minutes, calendar_id)
        return slots[0] if slots else None

    def get_upcoming_events(self, max_results=10, calendar_id="primary") -> list[dict]:
        now = datetime.now()
        future_events = [
            e for e in self.events
            if datetime.fromisoformat(e["start"]) > now
        ]
        future_events.sort(key=lambda e: e["start"])
        return future_events[:max_results]

    def get_events_on_date(self, date, calendar_id="primary") -> list[dict]:
        target = date.date() if isinstance(date, datetime) else date
        return [
            e for e in self.events
            if datetime.fromisoformat(e["start"]).date() == target
        ]
