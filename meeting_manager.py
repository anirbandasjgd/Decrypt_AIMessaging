"""
Smart Office Assistant - Meeting Manager
Orchestrates the full meeting scheduling flow with multi-turn conversation support.
Resolves participants, handles incomplete specs, manages confirmation, and creates events.
"""
from datetime import datetime, timedelta
from typing import Optional

from address_book import AddressBook
from calendar_service import CalendarService, MockCalendarService
from storage import MeetingStore
from nlu_engine import (
    parse_command, generate_followup_question,
    generate_confirmation_message, classify_confirmation
)
from config import DEFAULT_MEETING_DURATION_MINUTES, SMTP_EMAIL
from communication import send_meeting_invite_notification, send_meeting_invite_to_participants


# ─── Conversation States ─────────────────────────────────────────────────────

class ConversationState:
    IDLE = "idle"
    COLLECTING_INFO = "collecting_info"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_SLOT_CHOICE = "awaiting_slot_choice"
    AWAITING_DISAMBIGUATION = "awaiting_disambiguation"


class MeetingManager:
    """
    Manages the meeting scheduling conversation flow.
    Maintains state across multi-turn interactions.
    """

    def __init__(
        self,
        address_book: AddressBook,
        calendar_service: CalendarService | MockCalendarService,
        meeting_store: MeetingStore,
    ):
        self.address_book = address_book
        self.calendar = calendar_service
        self.meeting_store = meeting_store

        # Conversation state
        self.state = ConversationState.IDLE
        self.pending_meeting = {}          # Partially filled meeting details
        self.resolved_participants = []    # Resolved contact objects
        self.missing_fields = []           # Fields still needed
        self.disambiguation_context = {}   # For resolving ambiguous names
        self.conversation_history = []     # Message history for NLU context

    def reset(self):
        """Reset conversation state."""
        self.state = ConversationState.IDLE
        self.pending_meeting = {}
        self.resolved_participants = []
        self.missing_fields = []
        self.disambiguation_context = {}

    # ─── Main Processing Entry Point ─────────────────────────────────────

    # Intents that are clearly NOT continuation of a scheduling flow
    _NON_SCHEDULING_INTENTS = {
        "list_meetings", "search_mom", "upload_recording",
        "manage_contacts", "cancel_meeting", "reschedule_meeting",
        "add_attendees_to_meeting", "remove_attendees_from_meeting",
    }

    def process_message(self, user_message: str) -> dict:
        """
        Process a user message and return a response.
        Handles the full conversation flow including multi-turn interactions.
        
        Returns:
            dict with 'message' (str), 'action' (str), 'data' (dict)
        """
        # Add to conversation history
        self.conversation_history.append({"role": "user", "content": user_message})

        # If we're in a non-IDLE state, first check whether the user is
        # switching to an entirely different intent (e.g. "Show my meetings"
        # while we were collecting scheduling info).
        if self.state != ConversationState.IDLE:
            quick_parsed = parse_command(user_message, self.conversation_history)
            quick_intent = quick_parsed.get("intent", "general_chat")
            if quick_intent in self._NON_SCHEDULING_INTENTS:
                # User switched intent — abandon the current flow
                self.reset()
                return self._handle_new_command(user_message)

        # Route based on conversation state
        if self.state == ConversationState.AWAITING_CONFIRMATION:
            return self._handle_confirmation(user_message)

        if self.state == ConversationState.AWAITING_SLOT_CHOICE:
            return self._handle_slot_choice(user_message)

        if self.state == ConversationState.AWAITING_DISAMBIGUATION:
            return self._handle_disambiguation(user_message)

        if self.state == ConversationState.COLLECTING_INFO:
            return self._handle_info_collection(user_message)

        # IDLE state - parse fresh command
        return self._handle_new_command(user_message)

    # ─── Command Handlers ────────────────────────────────────────────────

    def _handle_new_command(self, user_message: str) -> dict:
        """Handle a new command from IDLE state."""
        parsed = parse_command(user_message, self.conversation_history)
        intent = parsed.get("intent", "general_chat")

        if intent == "schedule_meeting" or intent == "followup_meeting":
            return self._start_scheduling(parsed)

        elif intent == "list_meetings":
            return self._list_meetings()

        elif intent == "search_mom":
            query = parsed.get("search_query", user_message)
            return {"message": "", "action": "search_mom", "data": {"query": query}}

        elif intent == "upload_recording":
            return {
                "message": "To upload a recording, go to the **Meetings** page, find the meeting you want to add a recording to, and click **Upload Recording** inside it. This way the MoM will be linked to the correct meeting.",
                "action": "prompt_upload",
                "data": {}
            }

        elif intent == "manage_contacts":
            return {
                "message": "You can manage contacts from the Address Book page in the sidebar.",
                "action": "redirect",
                "data": {"page": "address_book"}
            }

        elif intent == "reschedule_meeting":
            return self._handle_reschedule(parsed, user_message)

        elif intent == "add_attendees_to_meeting":
            return self._handle_add_attendees(parsed, user_message)

        elif intent == "remove_attendees_from_meeting":
            return self._handle_remove_attendees(parsed)

        elif intent == "cancel_meeting":
            return {
                "message": parsed.get("response_message",
                                      "I can help with that. Could you tell me which meeting you'd like to cancel?"),
                "action": intent,
                "data": parsed
            }

        else:
            # General chat
            return {
                "message": parsed.get("response_message",
                                      "I'm your Smart Office Assistant! I can help you schedule meetings, "
                                      "manage contacts, transcribe recordings, and generate meeting minutes. "
                                      "What would you like to do?"),
                "action": "chat",
                "data": {}
            }

    def _start_scheduling(self, parsed: dict) -> dict:
        """Begin the meeting scheduling flow."""
        meeting = parsed.get("meeting_details", {})
        missing = parsed.get("missing_fields", [])

        self.pending_meeting = {
            "title": meeting.get("title", ""),
            "date": meeting.get("date", ""),
            "time": meeting.get("time", ""),
            "duration_minutes": meeting.get("duration_minutes", 0),
            "description": meeting.get("description", ""),
            "participants_raw": meeting.get("participants", []),
            "use_first_available": meeting.get("use_first_available", False),
            "is_followup": meeting.get("is_followup", False),
            "followup_reference": meeting.get("followup_reference", ""),
        }

        # Step 1: Resolve participants
        resolution = self._resolve_all_participants(self.pending_meeting["participants_raw"])

        if resolution["needs_disambiguation"]:
            self.state = ConversationState.AWAITING_DISAMBIGUATION
            self.disambiguation_context = resolution["disambiguation_needed"]
            return {
                "message": resolution["disambiguation_message"],
                "action": "awaiting_input",
                "data": {}
            }

        self.resolved_participants = resolution["resolved"]

        # Step 2: Check for missing fields
        self.missing_fields = self._compute_missing_fields()

        if self.missing_fields:
            self.state = ConversationState.COLLECTING_INFO
            question = generate_followup_question(self.missing_fields)
            return {
                "message": question,
                "action": "awaiting_input",
                "data": {"missing": self.missing_fields}
            }

        # Step 3: Handle "first available slot"
        if self.pending_meeting.get("use_first_available") and self.pending_meeting.get("date"):
            return self._find_and_offer_slot()

        # Step 4: All info available - confirm
        return self._present_confirmation()

    def _handle_info_collection(self, user_message: str) -> dict:
        """Handle responses during info collection phase."""
        # Re-parse with context of what we're collecting
        context_msg = (
            f"The user is providing missing information for a meeting. "
            f"Missing fields: {', '.join(self.missing_fields)}. "
            f"Current meeting details: {self.pending_meeting}. "
            f"User's response: {user_message}"
        )

        parsed = parse_command(context_msg, self.conversation_history)
        new_details = parsed.get("meeting_details", {})

        # Update pending meeting with new information
        if new_details.get("date") and "date" in self.missing_fields:
            self.pending_meeting["date"] = new_details["date"]
        if new_details.get("time") and "time" in self.missing_fields:
            self.pending_meeting["time"] = new_details["time"]
        if new_details.get("duration_minutes") and "duration" in self.missing_fields:
            self.pending_meeting["duration_minutes"] = new_details["duration_minutes"]
        if new_details.get("participants") and "participants" in self.missing_fields:
            self.pending_meeting["participants_raw"] = new_details["participants"]
            resolution = self._resolve_all_participants(new_details["participants"])
            self.resolved_participants = resolution["resolved"]
        if new_details.get("title") and "title" in self.missing_fields:
            self.pending_meeting["title"] = new_details["title"]

        # Also try direct parsing for simple responses
        self._try_direct_parse(user_message)

        # Check if we still have missing fields
        self.missing_fields = self._compute_missing_fields()

        if self.missing_fields:
            question = generate_followup_question(self.missing_fields)
            return {
                "message": question,
                "action": "awaiting_input",
                "data": {"missing": self.missing_fields}
            }

        # Handle first available slot
        if self.pending_meeting.get("use_first_available") and self.pending_meeting.get("date"):
            return self._find_and_offer_slot()

        return self._present_confirmation()

    def _handle_confirmation(self, user_message: str) -> dict:
        """Handle user's confirmation response."""
        decision = classify_confirmation(user_message)

        if decision == "confirmed":
            return self._execute_scheduling()
        elif decision == "cancelled":
            self.reset()
            return {
                "message": "Meeting scheduling cancelled. How else can I help?",
                "action": "cancelled",
                "data": {}
            }
        else:
            # Modification requested - go back to collecting info
            self.state = ConversationState.COLLECTING_INFO
            return self._handle_info_collection(user_message)

    def _handle_slot_choice(self, user_message: str) -> dict:
        """Handle user's choice of time slot."""
        # Parse the user's slot choice
        parsed = parse_command(
            f"The user is choosing a time slot. Available slots were offered. "
            f"User says: {user_message}",
            self.conversation_history
        )

        new_details = parsed.get("meeting_details", {})
        if new_details.get("time"):
            self.pending_meeting["time"] = new_details["time"]
        else:
            self._try_direct_parse(user_message)

        if self.pending_meeting.get("time"):
            self.state = ConversationState.IDLE
            return self._present_confirmation()

        return {
            "message": "I didn't catch the time. Could you specify which slot you'd like?",
            "action": "awaiting_input",
            "data": {}
        }

    def _handle_disambiguation(self, user_message: str) -> dict:
        """Handle disambiguation of ambiguous participant names."""
        # The user should be specifying which contact they mean
        ctx = self.disambiguation_context

        parsed = parse_command(
            f"The user is disambiguating a contact. Context: {ctx}. User says: {user_message}",
            self.conversation_history
        )

        # Try to resolve again
        new_participants = parsed.get("meeting_details", {}).get("participants", [])
        if new_participants:
            self.pending_meeting["participants_raw"].extend(new_participants)

        resolution = self._resolve_all_participants(self.pending_meeting["participants_raw"])

        if resolution["needs_disambiguation"]:
            self.disambiguation_context = resolution["disambiguation_needed"]
            return {
                "message": resolution["disambiguation_message"],
                "action": "awaiting_input",
                "data": {}
            }

        self.resolved_participants = resolution["resolved"]
        self.state = ConversationState.COLLECTING_INFO

        # Continue with missing fields check
        self.missing_fields = self._compute_missing_fields()
        if self.missing_fields:
            question = generate_followup_question(self.missing_fields)
            return {
                "message": question,
                "action": "awaiting_input",
                "data": {"missing": self.missing_fields}
            }

        return self._present_confirmation()

    # ─── Resolution & Validation ─────────────────────────────────────────

    def _resolve_all_participants(self, participants_raw: list[dict]) -> dict:
        """
        Resolve participant references to actual contacts.
        Handles: exact names, first names, department groups, disambiguation.
        """
        resolved = []
        needs_disambiguation = False
        disambiguation_needed = {}
        disambiguation_messages = []

        for p in participants_raw:
            name = p.get("name", "")
            department = p.get("department", "")
            is_group = p.get("is_department_group", False)

            if is_group and department:
                # "All members of Tech department"
                members = self.address_book.get_department_members(department)
                if members:
                    resolved.extend(members)
                else:
                    disambiguation_messages.append(
                        f"I couldn't find any contacts in the '{department}' department."
                    )
                continue

            # Resolve individual participant
            matches = self.address_book.resolve_participant(name, department)

            if len(matches) == 1:
                resolved.append(matches[0])
            elif len(matches) == 0:
                disambiguation_messages.append(
                    f"I couldn't find '{name}'"
                    + (f" in {department}" if department else "")
                    + " in the address book. Could you provide their full name?"
                )
                needs_disambiguation = True
                disambiguation_needed[name] = {"original": p, "matches": []}
            elif len(matches) > 1 and not department:
                # Multiple matches, need department or full name to disambiguate
                match_list = "\n".join(
                    f"  {i+1}. {self.address_book.format_contact(m)}"
                    for i, m in enumerate(matches)
                )
                disambiguation_messages.append(
                    f"I found multiple people named '{name}':\n{match_list}\n"
                    f"Which one did you mean? (Specify by number or full name)"
                )
                needs_disambiguation = True
                disambiguation_needed[name] = {"original": p, "matches": matches}
            else:
                resolved.extend(matches)

        # Remove duplicates
        seen_ids = set()
        unique_resolved = []
        for r in resolved:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                unique_resolved.append(r)

        return {
            "resolved": unique_resolved,
            "needs_disambiguation": needs_disambiguation,
            "disambiguation_needed": disambiguation_needed,
            "disambiguation_message": "\n\n".join(disambiguation_messages) if disambiguation_messages else "",
        }

    def _compute_missing_fields(self) -> list[str]:
        """Determine which required fields are still missing."""
        missing = []

        if not self.resolved_participants and not self.pending_meeting.get("participants_raw"):
            missing.append("participants")

        if not self.pending_meeting.get("date"):
            missing.append("date")

        if not self.pending_meeting.get("time") and not self.pending_meeting.get("use_first_available"):
            missing.append("time")

        # Duration is optional (has default), but it's better to ask
        if not self.pending_meeting.get("duration_minutes"):
            missing.append("duration")

        return missing

    def _try_direct_parse(self, text: str):
        """Try to directly parse simple responses for time/date/duration."""
        text_lower = text.strip().lower()

        # Try parsing common time formats
        import re

        # Time patterns: "2pm", "2:00 PM", "14:00", "at 3"
        time_patterns = [
            (r'(\d{1,2}):(\d{2})\s*(am|pm)', self._parse_ampm_time),
            (r'(\d{1,2})\s*(am|pm)', self._parse_ampm_simple),
            (r'(\d{1,2}):(\d{2})', self._parse_24h_time),
        ]

        if "time" in self.missing_fields and not self.pending_meeting.get("time"):
            for pattern, parser in time_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    time_str = parser(match)
                    if time_str:
                        self.pending_meeting["time"] = time_str
                        break

        # Duration patterns: "45 minutes", "1 hour", "30 min"
        if "duration" in self.missing_fields and not self.pending_meeting.get("duration_minutes"):
            dur_match = re.search(r'(\d+)\s*(min|minute|minutes|mins)', text_lower)
            if dur_match:
                self.pending_meeting["duration_minutes"] = int(dur_match.group(1))
            else:
                hour_match = re.search(r'(\d+(?:\.\d+)?)\s*(hour|hours|hr|hrs)', text_lower)
                if hour_match:
                    self.pending_meeting["duration_minutes"] = int(float(hour_match.group(1)) * 60)

            # "default" or "45 min default"
            if "default" in text_lower and not self.pending_meeting.get("duration_minutes"):
                self.pending_meeting["duration_minutes"] = DEFAULT_MEETING_DURATION_MINUTES

    @staticmethod
    def _parse_ampm_time(match) -> str:
        h, m, ampm = int(match.group(1)), int(match.group(2)), match.group(3)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"

    @staticmethod
    def _parse_ampm_simple(match) -> str:
        h, ampm = int(match.group(1)), match.group(2)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:00"

    @staticmethod
    def _parse_24h_time(match) -> str:
        h, m = int(match.group(1)), int(match.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
        return ""

    # ─── Slot Finding ────────────────────────────────────────────────────

    def _find_and_offer_slot(self) -> dict:
        """Find the first available slot and offer it to the user."""
        date_str = self.pending_meeting.get("date", "")
        duration = self.pending_meeting.get("duration_minutes", DEFAULT_MEETING_DURATION_MINUTES)

        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            self.state = ConversationState.COLLECTING_INFO
            self.missing_fields = ["date"]
            return {
                "message": "I couldn't parse the date. Could you specify the date more clearly?",
                "action": "awaiting_input",
                "data": {}
            }

        slot = self.calendar.find_first_available_slot(target_date, duration)

        if slot:
            self.pending_meeting["time"] = slot["start"]
            return self._present_confirmation()
        else:
            self.state = ConversationState.COLLECTING_INFO
            self.missing_fields = ["time"]
            return {
                "message": (f"I couldn't find any available {duration}-minute slots on "
                            f"{target_date.strftime('%A, %B %d, %Y')} during working hours. "
                            f"Would you like to try a different date or specify a time?"),
                "action": "awaiting_input",
                "data": {}
            }

    # ─── Confirmation & Execution ────────────────────────────────────────

    def _present_confirmation(self) -> dict:
        """Present the meeting details for user confirmation."""
        self.state = ConversationState.AWAITING_CONFIRMATION

        # Use default duration if still missing
        if not self.pending_meeting.get("duration_minutes"):
            self.pending_meeting["duration_minutes"] = DEFAULT_MEETING_DURATION_MINUTES

        # Generate title if missing
        if not self.pending_meeting.get("title"):
            participant_names = [p["name"] for p in self.resolved_participants[:3]]
            self.pending_meeting["title"] = f"Meeting with {', '.join(participant_names)}"

        msg = generate_confirmation_message(
            self.pending_meeting,
            self.resolved_participants
        )

        return {
            "message": msg,
            "action": "awaiting_confirmation",
            "data": {"meeting": self.pending_meeting, "participants": self.resolved_participants}
        }

    def _execute_scheduling(self) -> dict:
        """Execute the actual meeting scheduling."""
        date_str = self.pending_meeting.get("date", "")
        time_str = self.pending_meeting.get("time", "")
        duration = self.pending_meeting.get("duration_minutes", DEFAULT_MEETING_DURATION_MINUTES)

        try:
            meeting_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            self.reset()
            return {
                "message": "Sorry, there was an error parsing the date/time. Please try again.",
                "action": "error",
                "data": {}
            }

        # Get attendee emails
        attendee_emails = self.address_book.get_emails_for_contacts(self.resolved_participants)
        participant_names = [p["name"] for p in self.resolved_participants]

        # Create calendar event
        cal_result = self.calendar.create_event(
            title=self.pending_meeting["title"],
            start_datetime=meeting_dt,
            duration_minutes=duration,
            description=self.pending_meeting.get("description", ""),
            attendee_emails=attendee_emails,
        )

        # Store meeting record
        meeting_record = self.meeting_store.add_meeting(
            meeting_info={
                "title": self.pending_meeting["title"],
                "date": date_str,
                "time": time_str,
                "duration_minutes": duration,
                "participants": participant_names,
                "participant_emails": attendee_emails,
                "description": self.pending_meeting.get("description", ""),
                "calendar_event_id": cal_result.get("event_id", ""),
                "calendar_event_link": cal_result.get("html_link", ""),
            },
            parent_meeting_id=(
                self.pending_meeting.get("followup_reference")
                if self.pending_meeting.get("is_followup")
                else None
            ),
        )

        # Build response message
        if cal_result.get("success"):
            msg_parts = [
                f"Meeting scheduled successfully!\n",
                f"**{self.pending_meeting['title']}**",
                f"**Date:** {meeting_dt.strftime('%A, %B %d, %Y')}",
                f"**Time:** {meeting_dt.strftime('%I:%M %p')} ({duration} minutes)",
                f"**Participants:** {', '.join(participant_names)}",
            ]
            if cal_result.get("html_link"):
                msg_parts.append(f"\n[Open in Google Calendar]({cal_result['html_link']})")
            if cal_result.get("meet_link"):
                msg_parts.append(f"[Join Google Meet]({cal_result['meet_link']})")

            msg_parts.append(f"\nCalendar invites have been sent to all participants.")

            # Notify the organizer by email that the meeting invite is being sent
            if SMTP_EMAIL:
                send_meeting_invite_notification(
                    to_email=SMTP_EMAIL,
                    meeting_title=self.pending_meeting["title"],
                    date_str=date_str,
                    time_str=meeting_dt.strftime("%I:%M %p"),
                    participant_names=participant_names,
                    calendar_link=cal_result.get("html_link", ""),
                )

            # Send email notification to each participant (e.g. Anirban Das) so they receive the invite
            if attendee_emails:
                send_meeting_invite_to_participants(
                    attendee_emails=attendee_emails,
                    meeting_title=self.pending_meeting["title"],
                    date_str=date_str,
                    time_str=meeting_dt.strftime("%I:%M %p"),
                    duration_minutes=duration,
                    participant_names=participant_names,
                    calendar_link=cal_result.get("html_link", ""),
                    meet_link=cal_result.get("meet_link", ""),
                )
        else:
            msg_parts = [
                f"Meeting recorded locally but calendar invite could not be sent.",
                f"Error: {cal_result.get('error', 'Unknown')}",
                f"\n**{self.pending_meeting['title']}**",
                f"**Date:** {meeting_dt.strftime('%A, %B %d, %Y')}",
                f"**Time:** {meeting_dt.strftime('%I:%M %p')} ({duration} minutes)",
                f"**Participants:** {', '.join(participant_names)}",
            ]
            # Still notify participants by email so they receive the invite even when calendar fails
            if attendee_emails:
                send_meeting_invite_to_participants(
                    attendee_emails=attendee_emails,
                    meeting_title=self.pending_meeting["title"],
                    date_str=date_str,
                    time_str=meeting_dt.strftime("%I:%M %p"),
                    duration_minutes=duration,
                    participant_names=participant_names,
                    calendar_link=cal_result.get("html_link", ""),
                    meet_link=cal_result.get("meet_link", ""),
                )

        self.reset()
        return {
            "message": "\n".join(msg_parts),
            "action": "scheduled",
            "data": {
                "meeting_record": meeting_record,
                "calendar_result": cal_result,
            }
        }

    @staticmethod
    def _parse_flexible_datetime(text: str) -> tuple:
        """Try to parse date and optional time from natural text. Returns (date_str YYYY-MM-DD, time_str HH:MM) or (None, None)."""
        import re
        if not text or not text.strip():
            return (None, None)
        text = text.strip()
        # Try common patterns: "Mon 16th Feb 2026", "Monday 16 February 2026", "16 Feb 2026", "16th Feb 2026"
        months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
        # e.g. "Mon 16th Feb 2026" or "16 Feb 2026" or "Feb 16, 2026"
        for pattern, day_grp, month_grp, year_grp in [
            (r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})", 1, 2, 3),
            (r"(\d{1,2})(?:st|nd|rd|th)?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})", 1, 2, 3),
            (r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", 2, 1, 3),
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                day = int(m.group(day_grp))
                month_str = m.group(month_grp).lower()[:3]
                year = int(m.group(year_grp))
                month = months.get(month_str)
                if month and 1 <= day <= 31 and year >= 2000:
                    date_str = f"{year}-{month:02d}-{day:02d}"
                    # Try to find time in text: "3pm", "15:00", "9:30 am"
                    time_str = None
                    time_m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", text, re.IGNORECASE)
                    if time_m:
                        h, mi = int(time_m.group(1)), int(time_m.group(2))
                        if time_m.group(3) and time_m.group(3).lower() == "pm" and h != 12:
                            h += 12
                        elif time_m.group(3) and time_m.group(3).lower() == "am" and h == 12:
                            h = 0
                        time_str = f"{h:02d}:{mi:02d}"
                    else:
                        time_ampm = re.search(r"\b(\d{1,2})\s*(am|pm)\b", text, re.IGNORECASE)
                        if time_ampm:
                            h = int(time_ampm.group(1))
                            if time_ampm.group(2).lower() == "pm" and h != 12:
                                h += 12
                            elif time_ampm.group(2).lower() == "am" and h == 12:
                                h = 0
                            time_str = f"{h:02d}:00"
                    if not time_str:
                        time_str = "09:00"
                    return (date_str, time_str)
        return (None, None)

    def _handle_reschedule(self, parsed: dict, user_message: str = "") -> dict:
        """
        Reschedule an existing meeting: find it by meeting_ref_participants (or participants), update calendar + store.
        """
        meeting_details = parsed.get("meeting_details") or {}
        new_date = (meeting_details.get("date") or "").strip()
        new_time = (meeting_details.get("time") or "").strip()
        new_duration = meeting_details.get("duration_minutes") or DEFAULT_MEETING_DURATION_MINUTES
        # Use meeting_ref_participants to identify WHICH meeting (so "meeting with Nitin" works even with "and add X")
        ref_participants = meeting_details.get("meeting_ref_participants") or []
        participant_hints = meeting_details.get("participants") or []
        hint_names = [p.get("name", "").strip().lower() for p in ref_participants if p.get("name")]
        if not hint_names:
            hint_names = [p.get("name", "").strip().lower() for p in participant_hints if p.get("name")]

        # If date/time missing, try flexible parse from user message (e.g. "Mon 16th Feb 2026")
        if (not new_date or not new_time) and user_message:
            flex_date, flex_time = self._parse_flexible_datetime(user_message)
            if flex_date:
                new_date = new_date or flex_date
                new_time = new_time or flex_time

        # Only consider scheduled meetings
        scheduled = [m for m in self.meeting_store.meetings if m.get("status") == "scheduled"]
        if not scheduled:
            return {
                "message": "I couldn't find any scheduled meetings to reschedule.",
                "action": "chat",
                "data": {},
            }

        # Find meetings matching participant names (only ref hints)
        if hint_names:
            def matches(m):
                names_lower = [p.lower() for p in m.get("participants", [])]
                return any(h in p for p in names_lower for h in hint_names)
            candidates = [m for m in scheduled if matches(m)]
        else:
            candidates = scheduled

        if not candidates:
            return {
                "message": "I couldn't find a scheduled meeting matching that. Try listing meetings and rescheduling by saying e.g. 'Reschedule my meeting with [name] to tomorrow at 3pm'.",
                "action": "chat",
                "data": {},
            }

        meeting = sorted(candidates, key=lambda x: x.get("created_at", ""), reverse=True)[0]

        # Default time to 09:00 when only date is given
        if new_date and not new_time:
            new_time = "09:00"
        if not new_date:
            return {
                "message": f"I found **{meeting.get('title', 'Meeting')}** (with {', '.join(meeting.get('participants', [])[:3])}). "
                          f"What date and time should I reschedule it to? (e.g. 'Mon 16 Feb 2026' or 'Tomorrow at 3pm')",
                "action": "chat",
                "data": {},
            }

        try:
            meeting_dt = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return {
                "message": "I couldn't parse that date or time. Please use a format like '2025-02-15 14:00' or say e.g. 'Mon 16 Feb 2026'.",
                "action": "chat",
                "data": {},
            }

        duration = new_duration or meeting.get("duration_minutes", DEFAULT_MEETING_DURATION_MINUTES)
        event_id = meeting.get("calendar_event_id", "")
        calendar_updated = False
        cal_result = {}
        new_event_id = event_id
        new_event_link = meeting.get("calendar_event_link", "")

        if self.calendar.is_authenticated():
            # Only try update if we have a real (non-mock) event id; mock ids don't exist in Google
            can_update = event_id and not str(event_id).strip().lower().startswith("mock_")
            if can_update:
                cal_result = self.calendar.update_event(
                    event_id=event_id,
                    start_datetime=meeting_dt,
                    duration_minutes=duration,
                    send_notifications=True,
                )
                calendar_updated = cal_result.get("success", False)
                if calendar_updated:
                    new_event_id = cal_result.get("event_id", event_id)
                    new_event_link = cal_result.get("html_link", new_event_link)

            # If update failed (event not found, mock id, or 404), create a new event so invite goes out
            if not calendar_updated:
                create_result = self.calendar.create_event(
                    title=meeting.get("title", "Meeting"),
                    start_datetime=meeting_dt,
                    duration_minutes=duration,
                    description=meeting.get("description", ""),
                    attendee_emails=meeting.get("participant_emails") or [],
                    send_notifications=True,
                )
                if create_result.get("success"):
                    calendar_updated = True
                    cal_result = create_result
                    new_event_id = create_result.get("event_id", "")
                    new_event_link = create_result.get("html_link", "")
                    # Optionally notify participants by email (same as new meeting)
                    if SMTP_EMAIL and meeting.get("participant_emails"):
                        send_meeting_invite_to_participants(
                            attendee_emails=meeting["participant_emails"],
                            meeting_title=meeting.get("title", "Meeting"),
                            date_str=new_date,
                            time_str=meeting_dt.strftime("%I:%M %p"),
                            duration_minutes=duration,
                            participant_names=meeting.get("participants", []),
                            calendar_link=new_event_link,
                            meet_link=create_result.get("meet_link", ""),
                        )

        time_str_display = meeting_dt.strftime("%I:%M %p")
        date_str_display = meeting_dt.strftime("%A, %B %d, %Y")

        self.meeting_store.update_meeting(
            meeting["id"],
            date=new_date,
            time=new_time,
            duration_minutes=duration,
            calendar_event_id=new_event_id,
            calendar_event_link=new_event_link,
        )

        if calendar_updated:
            msg = (
                f"Done. I've rescheduled **{meeting.get('title', 'Meeting')}** to **{date_str_display}** at **{time_str_display}** "
                f"({duration} minutes). Calendar and invite updates have been sent to attendees."
            )
            if cal_result.get("html_link"):
                msg += f"\n\n[Open in Google Calendar]({cal_result['html_link']})"
        else:
            msg = (
                f"I've updated the meeting record to **{date_str_display}** at **{time_str_display}**. "
                f"The calendar event could not be updated (e.g. no Google Calendar link or error). "
                f"{cal_result.get('error', '')}"
            )

        return {
            "message": msg,
            "action": "rescheduled",
            "data": {"meeting": meeting, "calendar_result": cal_result},
        }

    def _find_meeting_by_participant_hints(self, hint_names: list[str], scheduled: list = None) -> Optional[dict]:
        """Find one scheduled meeting matching participant name hints. Returns meeting or None."""
        if scheduled is None:
            scheduled = [m for m in self.meeting_store.meetings if m.get("status") == "scheduled"]
        if not scheduled:
            return None
        if not hint_names:
            return sorted(scheduled, key=lambda x: x.get("created_at", ""), reverse=True)[0]
        def matches(m):
            names_lower = [p.lower() for p in m.get("participants", [])]
            return any(h in p for p in names_lower for h in hint_names)
        candidates = [m for m in scheduled if matches(m)]
        if not candidates:
            return None
        return sorted(candidates, key=lambda x: x.get("created_at", ""), reverse=True)[0]

    @staticmethod
    def _extract_add_target_from_message(message: str) -> list:
        """Fallback: extract person name(s) to add from phrases like 'Add Dummy1 contact to...' or 'Add Priya and Amit to...'."""
        import re
        if not message or not message.strip():
            return []
        msg = message.strip()
        # "Add X contact to ..." or "Add X to ..." or "add X to my meeting"
        m = re.search(r"\badd\s+(.+?)\s+(?:contact\s+)?to\s+(?:my\s+)?meeting", msg, re.IGNORECASE)
        if not m:
            m = re.search(r"\badd\s+(.+?)\s+to\s+", msg, re.IGNORECASE)
        if not m:
            return []
        names_str = m.group(1).strip()
        # Split on " and " or ","
        names = re.split(r"\s+and\s+|\s*,\s*", names_str, flags=re.IGNORECASE)
        return [{"name": n.strip()} for n in names if n.strip()]

    def _handle_add_attendees(self, parsed: dict, user_message: str = "") -> dict:
        """Add attendees to an existing meeting; update calendar and store, send invites to new attendees."""
        meeting_details = parsed.get("meeting_details") or {}
        ref_participants = meeting_details.get("meeting_ref_participants") or []
        to_add_raw = meeting_details.get("participants") or []
        ref_names = [p.get("name", "").strip().lower() for p in ref_participants if p.get("name")]
        # Fallback: if NLU didn't extract who to add (e.g. "Add Dummy1 contact to..."), try from message
        if not to_add_raw and user_message:
            to_add_raw = self._extract_add_target_from_message(user_message)
        if not ref_names and to_add_raw and user_message:
            # Try to get meeting ref from "meeting with X"
            import re
            m = re.search(r"meeting\s+with\s+(\w+(?:\s+\w+)?)", user_message, re.IGNORECASE)
            if m:
                ref_names = [m.group(1).strip().lower()]
        if not to_add_raw:
            return {
                "message": "Who would you like to add to the meeting? (e.g. 'Add Priya to my meeting with John' or 'Add Dummy1 contact to my meeting with Nitin')",
                "action": "chat",
                "data": {},
            }
        scheduled = [m for m in self.meeting_store.meetings if m.get("status") == "scheduled"]
        if not scheduled:
            return {"message": "I couldn't find any scheduled meetings.", "action": "chat", "data": {}}
        meeting = self._find_meeting_by_participant_hints(ref_names, scheduled)
        if not meeting:
            return {
                "message": "I couldn't find a scheduled meeting matching that. Try e.g. 'Add Priya to my meeting with [name of someone in the meeting]'.",
                "action": "chat",
                "data": {},
            }
        resolution = self._resolve_all_participants(to_add_raw)
        if resolution.get("needs_disambiguation"):
            return {
                "message": resolution.get("disambiguation_message", "Could you clarify who you want to add?"),
                "action": "chat",
                "data": {},
            }
        new_contacts = resolution.get("resolved", [])
        new_emails = self.address_book.get_emails_for_contacts(new_contacts)
        new_names = [c.get("name", "") for c in new_contacts]
        existing_emails = list(meeting.get("participant_emails") or [])
        existing_names = list(meeting.get("participants") or [])
        seen_emails = set(e.lower() for e in existing_emails)
        for email, name in zip(new_emails, new_names):
            if email and email.lower() not in seen_emails:
                existing_emails.append(email)
                existing_names.append(name)
                seen_emails.add(email.lower())
        if len(existing_emails) == len(meeting.get("participant_emails") or []):
            return {
                "message": "Those participants are already on the meeting, or I couldn't resolve their emails from the address book.",
                "action": "chat",
                "data": {},
            }
        event_id = meeting.get("calendar_event_id", "")
        can_update_calendar = event_id and not str(event_id).strip().lower().startswith("mock_") and self.calendar.is_authenticated()
        cal_result = {}
        if can_update_calendar:
            cal_result = self.calendar.update_event_attendees(
                event_id=event_id,
                attendee_emails=existing_emails,
                send_notifications=True,
            )
        elif self.calendar.is_authenticated() and (not event_id or str(event_id).strip().lower().startswith("mock_")):
            try:
                meeting_dt = datetime.strptime(f"{meeting.get('date', '')} {meeting.get('time', '00:00')}", "%Y-%m-%d %H:%M")
            except ValueError:
                meeting_dt = datetime.now()
            create_result = self.calendar.create_event(
                title=meeting.get("title", "Meeting"),
                start_datetime=meeting_dt,
                duration_minutes=meeting.get("duration_minutes", DEFAULT_MEETING_DURATION_MINUTES),
                description=meeting.get("description", ""),
                attendee_emails=existing_emails,
                send_notifications=True,
            )
            if create_result.get("success"):
                cal_result = create_result
                event_id = create_result.get("event_id", "")
                self.meeting_store.update_meeting(meeting["id"], calendar_event_id=event_id, calendar_event_link=create_result.get("html_link", ""))
        self.meeting_store.update_meeting(
            meeting["id"],
            participants=existing_names,
            participant_emails=existing_emails,
        )
        added_names = [n for n in new_names if n in existing_names]
        if cal_result.get("success") and added_names and SMTP_EMAIL:
            send_meeting_invite_to_participants(
                attendee_emails=new_emails,
                meeting_title=meeting.get("title", "Meeting"),
                date_str=meeting.get("date", ""),
                time_str=meeting.get("time", ""),
                duration_minutes=meeting.get("duration_minutes", 45),
                participant_names=existing_names,
                calendar_link=cal_result.get("html_link", meeting.get("calendar_event_link", "")),
                meet_link=cal_result.get("meet_link", ""),
            )
        msg = f"Done. I've added **{', '.join(added_names or new_names)}** to **{meeting.get('title', 'Meeting')}**. "
        if cal_result.get("success"):
            msg += "Calendar and invite updates have been sent."
        else:
            msg += f"Meeting record updated; calendar could not be updated. {cal_result.get('error', '')}"
        return {"message": msg, "action": "attendees_updated", "data": {"meeting": meeting}}

    def _handle_remove_attendees(self, parsed: dict) -> dict:
        """Remove attendees from an existing meeting; update calendar and store."""
        meeting_details = parsed.get("meeting_details") or {}
        ref_participants = meeting_details.get("meeting_ref_participants") or []
        to_remove_raw = meeting_details.get("participants") or []
        ref_names = [p.get("name", "").strip().lower() for p in ref_participants if p.get("name")]
        to_remove_names_lower = [p.get("name", "").strip().lower() for p in to_remove_raw if p.get("name")]
        if not to_remove_names_lower:
            return {
                "message": "Who would you like to remove from the meeting? (e.g. 'Remove John from my meeting with Nitin')",
                "action": "chat",
                "data": {},
            }
        scheduled = [m for m in self.meeting_store.meetings if m.get("status") == "scheduled"]
        if not scheduled:
            return {"message": "I couldn't find any scheduled meetings.", "action": "chat", "data": {}}
        meeting = self._find_meeting_by_participant_hints(ref_names, scheduled)
        if not meeting:
            return {
                "message": "I couldn't find a scheduled meeting matching that. Try e.g. 'Remove [name] from my meeting with [someone in the meeting]'.",
                "action": "chat",
                "data": {},
            }
        current_participants = list(meeting.get("participants") or [])
        current_emails = list(meeting.get("participant_emails") or [])
        def name_matches_any(name: str, hints: list) -> bool:
            n = name.lower()
            return any(h in n or n.startswith(h) for h in hints)
        keep_names = [p for p in current_participants if not name_matches_any(p, to_remove_names_lower)]
        keep_emails = [
            current_emails[i] for i in range(len(current_participants))
            if current_participants[i] in keep_names and i < len(current_emails) and current_emails[i]
        ]
        if len(keep_names) >= len(current_participants):
            return {
                "message": "I couldn't match those names to current attendees, or they're not on the meeting.",
                "action": "chat",
                "data": {},
            }
        removed = [p for p in current_participants if p not in keep_names]
        keep_emails_by_name = dict(zip(current_participants, current_emails)) if len(current_emails) >= len(current_participants) else {}
        keep_emails = [keep_emails_by_name.get(n, "") for n in keep_names if n in keep_emails_by_name]
        if len(keep_emails) < len(keep_names):
            keep_emails = current_emails[: len(keep_names)]
        event_id = meeting.get("calendar_event_id", "")
        can_update_calendar = event_id and not str(event_id).strip().lower().startswith("mock_") and self.calendar.is_authenticated()
        cal_result = {}
        if can_update_calendar:
            cal_result = self.calendar.update_event_attendees(
                event_id=event_id,
                attendee_emails=keep_emails,
                send_notifications=True,
            )
        self.meeting_store.update_meeting(
            meeting["id"],
            participants=keep_names,
            participant_emails=keep_emails,
        )
        msg = f"Done. I've removed **{', '.join(removed)}** from **{meeting.get('title', 'Meeting')}**. "
        if cal_result.get("success"):
            msg += "Calendar has been updated and they will no longer receive updates for this meeting."
        else:
            msg += "Meeting record updated." + (f" Calendar: {cal_result.get('error', '')}" if cal_result.get("error") else "")
        return {"message": msg, "action": "attendees_updated", "data": {"meeting": meeting}}

    def _list_meetings(self) -> dict:
        """List recent and upcoming meetings."""
        recent = self.meeting_store.get_recent_meetings(10)
        if not recent:
            return {
                "message": "No meetings scheduled yet.",
                "action": "list",
                "data": {"meetings": []}
            }

        lines = ["Here are your recent meetings:\n"]
        for m in recent:
            status_icon = {"scheduled": "📅", "completed": "✅", "cancelled": "❌"}.get(
                m.get("status", ""), "📅"
            )
            lines.append(
                f"{status_icon} **{m['title']}** - {m.get('date', '')} at {m.get('time', '')} "
                f"({m.get('duration_minutes', 45)} min)"
            )
            if m.get("participants"):
                lines.append(f"   Participants: {', '.join(m['participants'])}")

        return {
            "message": "\n".join(lines),
            "action": "list",
            "data": {"meetings": recent}
        }
