"""
Smart Office Assistant - Communication Module
Handles text-to-speech generation and email delivery.
"""
import os
import smtplib
import tempfile
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional

from openai import OpenAI
from config import (
    OPENAI_API_KEY, TTS_MODEL, TTS_VOICE, AUDIO_OUTPUT_DIR,
    SMTP_SERVER, SMTP_PORT, SMTP_EMAIL, SMTP_PASSWORD
)


client = OpenAI(api_key=OPENAI_API_KEY)


# ─── Text-to-Speech ─────────────────────────────────────────────────────────

def generate_tts_summary(
    text: str,
    filename: Optional[str] = None,
    voice: str = TTS_VOICE,
) -> dict:
    """
    Generate a text-to-speech audio file from text.
    
    Args:
        text: The text to convert to speech
        filename: Optional filename for the output
        voice: TTS voice to use (alloy, echo, fable, onyx, nova, shimmer)
    
    Returns:
        dict with 'success', 'filepath', 'filename'
    """
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"summary_{timestamp}.mp3"

    output_path = AUDIO_OUTPUT_DIR / filename

    try:
        response = client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=text,
        )

        # Stream to file
        response.stream_to_file(str(output_path))

        return {
            "success": True,
            "filepath": str(output_path),
            "filename": filename,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"TTS generation failed: {str(e)}"
        }


def generate_action_items_audio(action_items: list[dict], meeting_title: str = "") -> dict:
    """
    Generate a TTS audio summary of action items.
    
    Args:
        action_items: List of action item dicts with 'description', 'owner', 'deadline'
        meeting_title: Optional meeting title for context
    
    Returns:
        dict with 'success', 'filepath', 'filename', 'text'
    """
    if not action_items:
        return {"success": False, "error": "No action items to summarize"}

    # Build the narration text
    lines = []
    if meeting_title:
        lines.append(f"Action items from the meeting: {meeting_title}.")
    else:
        lines.append("Here are the action items from the meeting.")
    lines.append("")

    for i, item in enumerate(action_items, 1):
        owner = item.get("owner", "unassigned")
        description = item.get("description", "")
        deadline = item.get("deadline", "")

        line = f"Item {i}: {description}. Assigned to {owner}."
        if deadline and deadline.lower() != "tbd":
            line += f" Deadline: {deadline}."
        lines.append(line)

    text = " ".join(lines)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"action_items_{timestamp}.mp3"

    result = generate_tts_summary(text, filename)
    result["text"] = text
    return result


# ─── Email ───────────────────────────────────────────────────────────────────

def is_email_configured() -> bool:
    """Check if email credentials are configured."""
    return bool(SMTP_EMAIL and SMTP_PASSWORD)


def send_email(
    to_emails: list[str],
    subject: str,
    body_html: str,
    body_text: str = "",
    attachments: list[dict] = None,
    cc_emails: list[str] = None,
) -> dict:
    """
    Send an email via SMTP.
    
    Args:
        to_emails: List of recipient email addresses
        subject: Email subject
        body_html: HTML body content
        body_text: Plain text body (fallback)
        attachments: List of dicts with 'filepath' and 'filename'
        cc_emails: Optional CC recipients
    
    Returns:
        dict with 'success' and optional 'error'
    """
    if not is_email_configured():
        return {
            "success": False,
            "error": "Email not configured. Set SMTP_EMAIL and SMTP_PASSWORD in .env"
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = SMTP_EMAIL
        msg["To"] = ", ".join(to_emails)
        msg["Subject"] = subject

        if cc_emails:
            msg["Cc"] = ", ".join(cc_emails)

        # Add text and HTML parts
        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        # Add attachments
        if attachments:
            for att in attachments:
                filepath = att.get("filepath", "")
                att_filename = att.get("filename", os.path.basename(filepath))
                if filepath and os.path.exists(filepath):
                    with open(filepath, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={att_filename}"
                    )
                    msg.attach(part)

        # Send
        all_recipients = to_emails + (cc_emails or [])
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, all_recipients, msg.as_string())

        return {"success": True}

    except Exception as e:
        return {"success": False, "error": f"Email failed: {str(e)}"}


def send_mom_email(
    to_emails: list[str],
    mom_data: dict,
    audio_summary_path: Optional[str] = None,
) -> dict:
    """
    Send Minutes of Meeting email to attendees.
    
    Args:
        to_emails: List of attendee email addresses
        mom_data: MoM data dict
        audio_summary_path: Optional path to audio summary file
    
    Returns:
        dict with 'success' and optional 'error'
    """
    subject = f"Minutes of Meeting: {mom_data.get('title', 'Meeting')} - {mom_data.get('date', '')}"

    # Build HTML email
    html = _build_mom_email_html(mom_data, audio_summary_path)
    text = _build_mom_email_text(mom_data)

    attachments = []
    if audio_summary_path and os.path.exists(audio_summary_path):
        attachments.append({
            "filepath": audio_summary_path,
            "filename": "action_items_summary.mp3"
        })

    return send_email(to_emails, subject, html, text, attachments)


def send_meeting_invite_notification(
    to_email: str,
    meeting_title: str,
    date_str: str,
    time_str: str,
    participant_names: list,
    calendar_link: str = "",
) -> dict:
    """
    Send the user an email confirming that the meeting invite is being sent to participants.

    Args:
        to_email: Email address of the user who scheduled the meeting (e.g. app owner)
        meeting_title: Title of the meeting
        date_str: Meeting date (e.g. YYYY-MM-DD)
        time_str: Meeting time
        participant_names: List of participant names
        calendar_link: Optional link to open the event in calendar

    Returns:
        dict with 'success' and optional 'error'
    """
    if not to_email or not is_email_configured():
        return {"success": False, "error": "Email not configured or no recipient"}

    subject = f"Meeting invite sent: {meeting_title}"

    participants_line = ", ".join(participant_names) if participant_names else "—"

    html = f"""
    <html>
    <body style="font-family: sans-serif; max-width: 600px;">
        <h2 style="color: #667eea;">Meeting invite is being sent</h2>
        <p>Your meeting invite has been sent to the participants.</p>
        <table style="border-collapse: collapse; margin: 1em 0;">
            <tr><td style="padding: 6px 12px; font-weight: bold;">Meeting</td><td style="padding: 6px 12px;">{meeting_title}</td></tr>
            <tr><td style="padding: 6px 12px; font-weight: bold;">Date</td><td style="padding: 6px 12px;">{date_str}</td></tr>
            <tr><td style="padding: 6px 12px; font-weight: bold;">Time</td><td style="padding: 6px 12px;">{time_str}</td></tr>
            <tr><td style="padding: 6px 12px; font-weight: bold;">Participants</td><td style="padding: 6px 12px;">{participants_line}</td></tr>
        </table>
        <p>Calendar invites have been sent to all participants.</p>
        {f'<p><a href="{calendar_link}" style="color: #667eea;">Open in Calendar</a></p>' if calendar_link else ''}
        <p style="color: #666; font-size: 0.9em;">— Smart Office Assistant</p>
    </body>
    </html>
    """

    text = (
        f"Meeting invite is being sent.\n\n"
        f"Meeting: {meeting_title}\n"
        f"Date: {date_str}\n"
        f"Time: {time_str}\n"
        f"Participants: {participants_line}\n\n"
        "Calendar invites have been sent to all participants."
    )

    return send_email([to_email], subject, html, text)


def send_meeting_invite_to_participants(
    attendee_emails: list[str],
    meeting_title: str,
    date_str: str,
    time_str: str,
    duration_minutes: int = 45,
    participant_names: list = None,
    calendar_link: str = "",
    meet_link: str = "",
) -> dict:
    """
    Send each participant an email notifying them they have been invited to the meeting.
    Called when a meeting is scheduled so attendees receive an email even if calendar
    invites are not delivered (e.g. Mock Calendar) or in addition to calendar invites.

    Args:
        attendee_emails: List of participant email addresses
        meeting_title: Title of the meeting
        date_str: Meeting date
        time_str: Meeting time
        duration_minutes: Duration in minutes
        participant_names: Optional list of participant names for the email body
        calendar_link: Optional link to open in calendar
        meet_link: Optional Google Meet link

    Returns:
        dict with 'success', 'sent_count', and optional 'error'
    """
    if not attendee_emails or not is_email_configured():
        return {"success": False, "sent_count": 0, "error": "Email not configured or no attendees"}

    participants_line = ", ".join(participant_names) if participant_names else ", ".join(attendee_emails)

    subject = f"You're invited: {meeting_title}"

    html = f"""
    <html>
    <body style="font-family: sans-serif; max-width: 600px;">
        <h2 style="color: #667eea;">You're invited to a meeting</h2>
        <p>You have been invited to the following meeting.</p>
        <table style="border-collapse: collapse; margin: 1em 0;">
            <tr><td style="padding: 6px 12px; font-weight: bold;">Meeting</td><td style="padding: 6px 12px;">{meeting_title}</td></tr>
            <tr><td style="padding: 6px 12px; font-weight: bold;">Date</td><td style="padding: 6px 12px;">{date_str}</td></tr>
            <tr><td style="padding: 6px 12px; font-weight: bold;">Time</td><td style="padding: 6px 12px;">{time_str}</td></tr>
            <tr><td style="padding: 6px 12px; font-weight: bold;">Duration</td><td style="padding: 6px 12px;">{duration_minutes} minutes</td></tr>
            <tr><td style="padding: 6px 12px; font-weight: bold;">Participants</td><td style="padding: 6px 12px;">{participants_line}</td></tr>
        </table>
        {f'<p><a href="{calendar_link}" style="color: #667eea;">Add to Calendar</a></p>' if calendar_link else ''}
        {f'<p><a href="{meet_link}" style="color: #667eea;">Join Google Meet</a></p>' if meet_link else ''}
        <p style="color: #666; font-size: 0.9em;">— Smart Office Assistant</p>
    </body>
    </html>
    """

    text = (
        f"You're invited to a meeting.\n\n"
        f"Meeting: {meeting_title}\n"
        f"Date: {date_str}\n"
        f"Time: {time_str}\n"
        f"Duration: {duration_minutes} minutes\n"
        f"Participants: {participants_line}\n\n"
    )
    if calendar_link:
        text += f"Add to Calendar: {calendar_link}\n"
    if meet_link:
        text += f"Join Google Meet: {meet_link}\n"

    result = send_email(attendee_emails, subject, html, text)
    if result.get("success"):
        result["sent_count"] = len(attendee_emails)
    else:
        result["sent_count"] = 0
    return result


def _build_mom_email_html(mom_data: dict, audio_path: Optional[str] = None) -> str:
    """Build HTML email content for MoM."""
    title = mom_data.get("title", "Meeting")
    date = mom_data.get("date", "")
    attendees = mom_data.get("attendees", [])
    discussion = mom_data.get("key_discussion_points", [])
    decisions = mom_data.get("decisions", [])
    action_items = mom_data.get("action_items", [])

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #333;">
        <div style="background: linear-gradient(135deg, #667eea, #764ba2); padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0;">Minutes of Meeting</h1>
            <p style="color: #e0e0e0; margin: 5px 0 0 0;">{title}</p>
        </div>
        
        <div style="padding: 20px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 8px 8px;">
            <p><strong>Date:</strong> {date}</p>
            <p><strong>Attendees:</strong> {', '.join(attendees)}</p>
    """

    if discussion:
        html += "<h2 style='color: #667eea;'>Key Discussion Points</h2><ol>"
        for point in discussion:
            html += f"<li>{point}</li>"
        html += "</ol>"

    if decisions:
        html += "<h2 style='color: #667eea;'>Decisions Made</h2><ol>"
        for d in decisions:
            html += f"<li>{d}</li>"
        html += "</ol>"

    if action_items:
        html += """
        <h2 style='color: #667eea;'>Action Items</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="background: #f5f5f5;">
                <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">#</th>
                <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Action Item</th>
                <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Owner</th>
                <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Deadline</th>
            </tr>
        """
        for i, item in enumerate(action_items, 1):
            html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">{i}</td>
                <td style="padding: 8px; border: 1px solid #ddd;">{item.get('description', '')}</td>
                <td style="padding: 8px; border: 1px solid #ddd;">{item.get('owner', 'TBD')}</td>
                <td style="padding: 8px; border: 1px solid #ddd;">{item.get('deadline', 'TBD')}</td>
            </tr>
            """
        html += "</table>"

    if audio_path:
        html += """
        <div style="margin-top: 20px; padding: 15px; background: #f0f4ff; border-radius: 8px;">
            <p><strong>📎 Audio Summary:</strong> An audio summary of action items is attached to this email.</p>
        </div>
        """

    html += """
            <hr style="margin-top: 30px; border: none; border-top: 1px solid #e0e0e0;">
            <p style="color: #999; font-size: 12px;">
                Generated by Smart Office Assistant
            </p>
        </div>
    </body>
    </html>
    """
    return html


def _build_mom_email_text(mom_data: dict) -> str:
    """Build plain text email content for MoM."""
    lines = [
        f"MINUTES OF MEETING: {mom_data.get('title', 'Meeting')}",
        f"Date: {mom_data.get('date', '')}",
        f"Attendees: {', '.join(mom_data.get('attendees', []))}",
        "",
    ]

    if mom_data.get("key_discussion_points"):
        lines.append("KEY DISCUSSION POINTS:")
        for i, point in enumerate(mom_data["key_discussion_points"], 1):
            lines.append(f"  {i}. {point}")
        lines.append("")

    if mom_data.get("decisions"):
        lines.append("DECISIONS:")
        for i, d in enumerate(mom_data["decisions"], 1):
            lines.append(f"  {i}. {d}")
        lines.append("")

    if mom_data.get("action_items"):
        lines.append("ACTION ITEMS:")
        for i, item in enumerate(mom_data["action_items"], 1):
            lines.append(
                f"  {i}. {item.get('description', '')} "
                f"[Owner: {item.get('owner', 'TBD')}] "
                f"[Deadline: {item.get('deadline', 'TBD')}]"
            )
        lines.append("")

    return "\n".join(lines)
