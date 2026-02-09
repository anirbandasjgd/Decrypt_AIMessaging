"""
Smart Office Assistant - Minutes of Meeting Generator
Generates structured MoM from transcripts, extracts action items.
"""
import json
from datetime import datetime
from openai import OpenAI
from config import OPENAI_API_KEY, MOM_MODEL, debug_log


client = OpenAI(api_key=OPENAI_API_KEY)


MOM_SYSTEM_PROMPT = """You are an expert meeting minutes generator. Given a meeting transcript, 
you must produce a structured Minutes of Meeting (MoM) document.

Extract the following information:
1. **Meeting Title/Subject** - Infer from context if not explicitly stated
2. **Key Discussion Points** - Main topics discussed, summarized clearly
3. **Decisions Made** - Any decisions or conclusions reached
4. **Action Items** - Specific tasks assigned to people, with:
   - Description of the task
   - Owner (person assigned)
   - Deadline (if mentioned, otherwise "TBD")
5. **Summary** - Brief overall summary of the meeting

IMPORTANT RULES:
- Be concise but comprehensive
- Use professional language
- If speaker names are identifiable, attribute statements correctly
- Clearly separate discussion points from decisions from action items
- If action items don't have clear owners, mark as "TBD"
- Format dates consistently

Respond ONLY with valid JSON matching the required schema."""


MOM_EXTRACTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_mom",
            "description": "Generate structured Minutes of Meeting from a transcript",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Meeting title/subject"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief overall summary (2-3 sentences)"
                    },
                    "key_discussion_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Main topics discussed"
                    },
                    "decisions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Decisions made during the meeting"
                    },
                    "action_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "owner": {"type": "string"},
                                "deadline": {"type": "string"},
                                "priority": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"]
                                }
                            },
                            "required": ["description", "owner"]
                        },
                        "description": "Action items with assigned owners"
                    },
                    "attendees_mentioned": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of people mentioned or identified in the transcript"
                    },
                    "next_steps": {
                        "type": "string",
                        "description": "Any mentioned next steps or follow-up meeting plans"
                    }
                },
                "required": ["title", "summary", "key_discussion_points", "action_items"]
            }
        }
    }
]


def generate_mom_from_transcript(
    transcript: str,
    meeting_title: str = "",
    attendees: list[str] = None,
    meeting_date: str = "",
) -> dict:
    """
    Generate structured Minutes of Meeting from a transcript.
    
    Args:
        transcript: The meeting transcript text
        meeting_title: Optional meeting title (will be inferred if not provided)
        attendees: Optional list of known attendee names
        meeting_date: Optional meeting date
    
    Returns:
        dict with MoM data including action_items, discussion_points, etc.
    """
    context = f"Transcript:\n{transcript}"
    if meeting_title:
        context = f"Meeting Title: {meeting_title}\n{context}"
    if attendees:
        context = f"Known Attendees: {', '.join(attendees)}\n{context}"
    if meeting_date:
        context = f"Meeting Date: {meeting_date}\n{context}"

    mom_messages = [
        {"role": "system", "content": MOM_SYSTEM_PROMPT},
        {"role": "user", "content": context}
    ]
    debug_log("[OpenAI MoM generate_mom_from_transcript] Request: model=%s, system_prompt_len=%d, user_content_len=%d"
                 % (MOM_MODEL, len(MOM_SYSTEM_PROMPT), len(context)))
    debug_log("[OpenAI MoM generate_mom_from_transcript] User content (first 500 chars): %s" % (context[:500] + "..." if len(context) > 500 else context))
    try:
        response = client.chat.completions.create(
            model=MOM_MODEL,
            messages=mom_messages,
            tools=MOM_EXTRACTION_TOOLS,
            tool_choice={"type": "function", "function": {"name": "generate_mom"}},
            temperature=0.2,
        )

        tool_call = response.choices[0].message.tool_calls[0]
        mom_data = json.loads(tool_call.function.arguments)
        debug_log("[OpenAI MoM generate_mom_from_transcript] Response: tool_call_args=%s" % mom_data)

        # Enrich with metadata
        mom_data["date"] = meeting_date or datetime.now().strftime("%Y-%m-%d")
        mom_data["attendees"] = attendees or mom_data.get("attendees_mentioned", [])
        mom_data["transcript"] = transcript

        # Add status to action items
        for item in mom_data.get("action_items", []):
            if "status" not in item:
                item["status"] = "Pending"
            if "deadline" not in item:
                item["deadline"] = "TBD"
            if "priority" not in item:
                item["priority"] = "medium"

        return {
            "success": True,
            "mom": mom_data
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"MoM generation failed: {str(e)}"
        }


def generate_mom_content_text(mom_data: dict) -> str:
    """Generate a formatted text version of the MoM."""
    lines = []
    lines.append(f"# Minutes of Meeting: {mom_data.get('title', 'Meeting')}")
    lines.append(f"\n**Date:** {mom_data.get('date', 'N/A')}")

    if mom_data.get("attendees"):
        lines.append(f"**Attendees:** {', '.join(mom_data['attendees'])}")

    lines.append(f"\n## Summary\n{mom_data.get('summary', 'N/A')}")

    if mom_data.get("key_discussion_points"):
        lines.append("\n## Key Discussion Points")
        for i, point in enumerate(mom_data["key_discussion_points"], 1):
            lines.append(f"{i}. {point}")

    if mom_data.get("decisions"):
        lines.append("\n## Decisions Made")
        for i, decision in enumerate(mom_data["decisions"], 1):
            lines.append(f"{i}. {decision}")

    if mom_data.get("action_items"):
        lines.append("\n## Action Items")
        lines.append("| # | Action Item | Owner | Deadline | Priority | Status |")
        lines.append("|---|-----------|-------|----------|----------|--------|")
        for i, item in enumerate(mom_data["action_items"], 1):
            lines.append(
                f"| {i} | {item.get('description', '')} | "
                f"{item.get('owner', 'TBD')} | "
                f"{item.get('deadline', 'TBD')} | "
                f"{item.get('priority', 'medium').title()} | "
                f"{item.get('status', 'Pending')} |"
            )

    if mom_data.get("next_steps"):
        lines.append(f"\n## Next Steps\n{mom_data['next_steps']}")

    return "\n".join(lines)


def extract_action_items_summary(mom_data: dict) -> str:
    """Generate a concise text summary of action items for TTS."""
    items = mom_data.get("action_items", [])
    if not items:
        return "No action items were identified from this meeting."

    title = mom_data.get("title", "the meeting")
    lines = [f"Action items from {title}:"]

    for i, item in enumerate(items, 1):
        owner = item.get("owner", "unassigned")
        desc = item.get("description", "")
        deadline = item.get("deadline", "")
        line = f"Item {i}: {desc}. Assigned to {owner}."
        if deadline and deadline.upper() != "TBD":
            line += f" Due by {deadline}."
        lines.append(line)

    return " ".join(lines)
