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
from config import DEFAULT_MEETING_DURATION_MINUTES


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
        "manage_contacts", "cancel_meeting",
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

        elif intent in ("cancel_meeting", "reschedule_meeting"):
            return {
                "message": parsed.get("response_message",
                                      "I can help with that. Could you tell me which meeting you'd like to "
                                      f"{'cancel' if intent == 'cancel_meeting' else 'reschedule'}?"),
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
        else:
            msg_parts = [
                f"Meeting recorded locally but calendar invite could not be sent.",
                f"Error: {cal_result.get('error', 'Unknown')}",
                f"\n**{self.pending_meeting['title']}**",
                f"**Date:** {meeting_dt.strftime('%A, %B %d, %Y')}",
                f"**Time:** {meeting_dt.strftime('%I:%M %p')} ({duration} minutes)",
                f"**Participants:** {', '.join(participant_names)}",
            ]

        self.reset()
        return {
            "message": "\n".join(msg_parts),
            "action": "scheduled",
            "data": {
                "meeting_record": meeting_record,
                "calendar_result": cal_result,
            }
        }

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
