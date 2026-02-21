"""
Smart Office Assistant - Natural Language Understanding Engine
Parses natural language commands into structured meeting actions using OpenAI.
"""
import json
from datetime import datetime
from openai import OpenAI
from config import OPENAI_API_KEY, NLU_MODEL, debug_log


client = OpenAI(api_key=OPENAI_API_KEY)

# ─── Intent Classification & Entity Extraction ──────────────────────────────

SYSTEM_PROMPT = """You are the NLU engine for a Smart Office Assistant. Your job is to understand 
user commands and extract structured information for meeting scheduling and management.

Today's date is {today}. The current day is {day_of_week}.

IMPORTANT RULES:
1. For date references like "next Tuesday", "coming Monday", "Mon 16th Feb 2026", calculate the actual date and ALWAYS output it in YYYY-MM-DD format in the date field (e.g. 2026-02-16).
2. "Thursday after next week" means the Thursday of the week AFTER next week.
3. "Coming week Monday" means the Monday of the upcoming week (next Monday).
4. When a user says "all members of [Department]", set is_department_group to true.
5. When a user mentions someone "from [Department]", include their department for disambiguation.
6. If time is NOT specified, mark it as missing in missing_fields.
7. If date is NOT specified, mark it as missing in missing_fields.
8. If "first available slot" or similar is mentioned, set use_first_available to true.
9. Duration defaults can be left empty if not mentioned - the system will ask or use default.
10. FOLLOW-UP MEETINGS: When the user says "follow up", "follow-up", or "followup" meeting, set is_followup to true and use intent "followup_meeting". Put the reference to the original meeting in followup_reference — include participant names, date cues (e.g. "yesterday", "last Tuesday"), and time cues (e.g. "at 6:30") so the system can match it.
    CRITICAL: The date/time fields in meeting_details must ONLY contain the NEW follow-up meeting's scheduled date/time. Any date/time that describes the ORIGINAL meeting (e.g. "my meeting yesterday at 6:30") belongs ONLY in followup_reference, NOT in the date/time fields. If the user does NOT specify when the new follow-up should be scheduled, mark date and/or time as missing_fields.
    Example: "Create a follow-up meeting with Sajith on my meeting with him today at 6:30" → followup_reference="meeting with Sajith today at 6:30", date and time should be in missing_fields (the user did NOT say when the NEW meeting should be), participants=[{{name:"Sajith"}}], is_followup=true.
    Example: "Schedule a follow-up with Sajith for tomorrow at 3pm, on our meeting yesterday" → followup_reference="meeting with Sajith yesterday", date="(tomorrow's date)", time="15:00", participants=[{{name:"Sajith"}}], is_followup=true.
11. Detect the intent: schedule_meeting, reschedule_meeting, cancel_meeting,
    add_attendees_to_meeting, remove_attendees_from_meeting,
    upload_recording, search_mom, manage_contacts, list_meetings, general_chat, followup_meeting.
12. For names, preserve them as spoken. If only first name given, include just first name.
13. Parse meeting title/subject if mentioned, otherwise generate a reasonable one.
14. For reschedule_meeting: use meeting_ref_participants to identify WHICH meeting (e.g. "my meeting with Nitin" -> meeting_ref_participants: [{{name: "Nitin"}}]). Put the new date and time in date (YYYY-MM-DD) and time (HH:MM). Ignore extra text like "and add X" for finding the meeting.
15. For add_attendees_to_meeting: "Add X contact to my meeting with Y" or "Add X to my meeting with Y" means participants: [{{name: "X"}}] (who to add) and meeting_ref_participants: [{{name: "Y"}}] (which meeting). Always fill both when the user names someone to add and someone in the meeting.
16. For remove_attendees_from_meeting: "Remove X from my meeting with Y" means participants: [{{name: "X"}}] (who to remove) and meeting_ref_participants: [{{name: "Y"}}] (which meeting).
17. CRITICAL - Latest message only: The intent and ALL extracted fields (participants, meeting_ref_participants, date, time, etc.) must be determined ONLY from the **most recent** user message. Earlier messages are for context only (e.g. to resolve "that meeting"). If the most recent message is "add Dummy1 to my meeting with Nitin", intent MUST be add_attendees_to_meeting with participants: [{{name: "Dummy1"}}] and meeting_ref_participants: [{{name: "Nitin"}}], even if previous messages were about rescheduling. Do not carry over intent from earlier turns.

Respond ONLY with valid JSON matching the required schema."""


EXTRACTION_FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "process_command",
            "description": "Process a user command and extract structured information",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": [
                            "schedule_meeting", "reschedule_meeting", "cancel_meeting",
                            "add_attendees_to_meeting", "remove_attendees_from_meeting",
                            "upload_recording", "search_mom", "manage_contacts",
                            "list_meetings", "general_chat", "followup_meeting"
                        ],
                        "description": "The primary intent of the user's command"
                    },
                    "meeting_details": {
                        "type": "object",
                        "description": "Extracted meeting details (for scheduling intents)",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Meeting title or subject"
                            },
                            "participants": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string", "description": "Person's name as mentioned"},
                                        "department": {"type": "string", "description": "Department if mentioned"},
                                        "is_department_group": {
                                            "type": "boolean",
                                            "description": "True if referring to all members of a department"
                                        }
                                    },
                                    "required": ["name"]
                                },
                                "description": "List of participants"
                            },
                            "date": {
                                "type": "string",
                                "description": "Resolved date in YYYY-MM-DD format, or empty if not specified"
                            },
                            "time": {
                                "type": "string",
                                "description": "Time in HH:MM (24h) format, or empty if not specified"
                            },
                            "duration_minutes": {
                                "type": "integer",
                                "description": "Duration in minutes, 0 if not specified"
                            },
                            "description": {
                                "type": "string",
                                "description": "Meeting description or agenda if mentioned"
                            },
                            "use_first_available": {
                                "type": "boolean",
                                "description": "True if user wants the first available time slot"
                            },
                            "is_followup": {
                                "type": "boolean",
                                "description": "True if this is a follow-up to a previous meeting"
                            },
                            "followup_reference": {
                                "type": "string",
                                "description": "Reference to the previous meeting if this is a follow-up"
                            },
                            "meeting_ref_participants": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "department": {"type": "string"}
                                    },
                                    "required": ["name"]
                                },
                                "description": "For add/remove attendees: participants who identify WHICH meeting (e.g. 'meeting with John' -> [{name: 'John'}]). participants array is then who to add or remove."
                            }
                        }
                    },
                    "missing_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of required fields that are missing: date, time, duration, participants, title"
                    },
                    "search_query": {
                        "type": "string",
                        "description": "Search query for MoM search or meeting search intents"
                    },
                    "response_message": {
                        "type": "string",
                        "description": "A natural language response to show the user (for general_chat or acknowledgments)"
                    }
                },
                "required": ["intent"]
            }
        }
    }
]


def parse_command(user_message: str, conversation_history: list[dict] = None) -> dict:
    """
    Parse a user command and extract structured information.
    Returns a dict with intent, meeting_details, missing_fields, etc.
    """
    today = datetime.now()
    system_msg = SYSTEM_PROMPT.format(
        today=today.strftime("%Y-%m-%d"),
        day_of_week=today.strftime("%A")
    )

    messages = [{"role": "system", "content": system_msg}]

    # Include conversation history for context (multi-turn)
    if conversation_history:
        for msg in conversation_history[-10:]:  # Last 10 messages for context
            messages.append(msg)

    # Emphasize that intent and extraction must come from this latest message only
    current_message = user_message.strip()
    if conversation_history:
        current_message = "[Current message - determine intent and entities from this only]: " + current_message
    messages.append({"role": "user", "content": current_message})

    debug_log("[OpenAI NLU parse_command] Request: model=%s, messages=%s" % (NLU_MODEL, messages))
    try:
        response = client.chat.completions.create(
            model=NLU_MODEL,
            messages=messages,
            tools=EXTRACTION_FUNCTIONS,
            tool_choice={"type": "function", "function": {"name": "process_command"}},
            temperature=0.1,
        )
        tool_call = response.choices[0].message.tool_calls[0]
        result = json.loads(tool_call.function.arguments)
        debug_log("[OpenAI NLU parse_command] Response: intent=%s, result=%s" % (result.get("intent"), result))
        return result

    except Exception as e:
        return {
            "intent": "general_chat",
            "response_message": f"I had trouble understanding that. Could you rephrase? (Error: {str(e)})",
            "missing_fields": []
        }


def generate_followup_question(missing_fields: list[str], context: dict = None) -> str:
    """Generate a natural follow-up question for missing information."""
    questions = []

    field_questions = {
        "date": "What date would you like to schedule this meeting?",
        "time": "What time should the meeting be scheduled?",
        "duration": "How long should the meeting be? (Default is 45 minutes)",
        "participants": "Who should attend this meeting?",
        "title": "What should the meeting be about / what title would you like?",
    }

    for field in missing_fields:
        if field in field_questions:
            questions.append(field_questions[field])

    if not questions:
        return "Could you provide more details about the meeting?"

    if len(questions) == 1:
        return questions[0]

    # Use AI to combine questions naturally
    followup_messages = [
        {"role": "system", "content": "Combine these questions into one natural, "
         "friendly follow-up message. Be concise."},
        {"role": "user", "content": "\n".join(questions)}
    ]
    debug_log("[OpenAI NLU generate_followup_question] Request: model=%s, messages=%s" % (NLU_MODEL, followup_messages))
    try:
        response = client.chat.completions.create(
            model=NLU_MODEL,
            messages=followup_messages,
            temperature=0.7,
            max_tokens=150
        )
        content = response.choices[0].message.content
        debug_log("[OpenAI NLU generate_followup_question] Response: %s" % content)
        return content
    except Exception:
        return " Also, ".join(questions)


def generate_confirmation_message(meeting_details: dict, resolved_participants: list[dict]) -> str:
    """Generate a confirmation message for the user to review before scheduling."""
    participant_names = []
    for p in resolved_participants:
        name = p.get("name", "Unknown")
        dept = p.get("department", "")
        if dept:
            participant_names.append(f"{name} ({dept})")
        else:
            participant_names.append(name)

    msg_parts = [
        "Here's what I have for the meeting:\n",
        f"**Title:** {meeting_details.get('title', 'Meeting')}",
        f"**Date:** {meeting_details.get('date', 'TBD')}",
        f"**Time:** {meeting_details.get('time', 'TBD')}",
        f"**Duration:** {meeting_details.get('duration_minutes', 45)} minutes",
        f"**Participants:** {', '.join(participant_names)}",
    ]

    if meeting_details.get("description"):
        msg_parts.append(f"**Description:** {meeting_details['description']}")

    if meeting_details.get("is_followup") and meeting_details.get("parent_meeting_title"):
        msg_parts.append(f"🔗 **Follow-up to:** {meeting_details['parent_meeting_title']}")

    msg_parts.append("\nShall I go ahead and schedule this? (Yes/No)")
    return "\n".join(msg_parts)


def classify_confirmation(user_message: str) -> str:
    """Classify if a user message is a confirmation, denial, or modification."""
    msg_lower = user_message.strip().lower()

    # Quick pattern matching
    if msg_lower in ("yes", "y", "yeah", "yep", "sure", "go ahead", "confirm",
                     "ok", "okay", "schedule it", "do it", "please", "yes please"):
        return "confirmed"

    if msg_lower in ("no", "n", "nope", "cancel", "nevermind", "never mind",
                     "forget it", "stop"):
        return "cancelled"

    # Use AI for ambiguous cases
    classify_messages = [
        {"role": "system", "content": "Classify the user's response as one of: "
         "'confirmed' (they want to proceed), 'cancelled' (they want to stop), "
         "or 'modification' (they want to change something). "
         "Respond with ONLY one word."},
        {"role": "user", "content": user_message}
    ]
    debug_log("[OpenAI NLU classify_confirmation] Request: model=%s, messages=%s" % (NLU_MODEL, classify_messages))
    try:
        response = client.chat.completions.create(
            model=NLU_MODEL,
            messages=classify_messages,
            temperature=0,
            max_tokens=10
        )
        result = response.choices[0].message.content.strip().lower()
        debug_log("[OpenAI NLU classify_confirmation] Response: %s" % result)
        if result in ("confirmed", "cancelled", "modification"):
            return result
        return "modification"
    except Exception:
        return "modification"
