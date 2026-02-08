"""
Smart Office Assistant - Natural Language Understanding Engine
Parses natural language commands into structured meeting actions using OpenAI.
"""
import json
from datetime import datetime
from openai import OpenAI
from config import OPENAI_API_KEY, NLU_MODEL


client = OpenAI(api_key=OPENAI_API_KEY)

# ─── Intent Classification & Entity Extraction ──────────────────────────────

SYSTEM_PROMPT = """You are the NLU engine for a Smart Office Assistant. Your job is to understand 
user commands and extract structured information for meeting scheduling and management.

Today's date is {today}. The current day is {day_of_week}.

IMPORTANT RULES:
1. For date references like "next Tuesday", "coming Monday", calculate the actual date.
2. "Thursday after next week" means the Thursday of the week AFTER next week.
3. "Coming week Monday" means the Monday of the upcoming week (next Monday).
4. When a user says "all members of [Department]", set is_department_group to true.
5. When a user mentions someone "from [Department]", include their department for disambiguation.
6. If time is NOT specified, mark it as missing in missing_fields.
7. If date is NOT specified, mark it as missing in missing_fields.
8. If "first available slot" or similar is mentioned, set use_first_available to true.
9. Duration defaults can be left empty if not mentioned - the system will ask or use default.
10. Always identify if this is a follow-up to a previous meeting.
11. Detect the intent: schedule_meeting, reschedule_meeting, cancel_meeting, 
    upload_recording, search_mom, manage_contacts, list_meetings, general_chat.
12. For names, preserve them as spoken. If only first name given, include just first name.
13. Parse meeting title/subject if mentioned, otherwise generate a reasonable one.

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

    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=NLU_MODEL,
            messages=messages,
            tools=EXTRACTION_FUNCTIONS,
            tool_choice={"type": "function", "function": {"name": "process_command"}},
            temperature=0.1,
        )

        # Extract the function call result
        tool_call = response.choices[0].message.tool_calls[0]
        result = json.loads(tool_call.function.arguments)
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
    try:
        response = client.chat.completions.create(
            model=NLU_MODEL,
            messages=[
                {"role": "system", "content": "Combine these questions into one natural, "
                 "friendly follow-up message. Be concise."},
                {"role": "user", "content": "\n".join(questions)}
            ],
            temperature=0.7,
            max_tokens=150
        )
        return response.choices[0].message.content
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
    try:
        response = client.chat.completions.create(
            model=NLU_MODEL,
            messages=[
                {"role": "system", "content": "Classify the user's response as one of: "
                 "'confirmed' (they want to proceed), 'cancelled' (they want to stop), "
                 "or 'modification' (they want to change something). "
                 "Respond with ONLY one word."},
                {"role": "user", "content": user_message}
            ],
            temperature=0,
            max_tokens=10
        )
        result = response.choices[0].message.content.strip().lower()
        if result in ("confirmed", "cancelled", "modification"):
            return result
        return "modification"
    except Exception:
        return "modification"
