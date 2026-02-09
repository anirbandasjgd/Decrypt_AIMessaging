"""
Smart Office Assistant - Main Streamlit Application
A web-based assistant for meeting management, scheduling, transcription, and MoM generation.
"""
import sys
import os
import json
import streamlit as st
from datetime import datetime
from pathlib import Path

# Ensure the smart_office_assistant directory is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import APP_TITLE, APP_ICON, GOOGLE_CREDENTIALS_FILE, DEBUG_LOGGING
import config as config_module
from address_book import AddressBook
from calendar_service import CalendarService, MockCalendarService
from storage import MeetingStore, MoMStore
from meeting_manager import MeetingManager
from nlu_engine import parse_command
from transcription_service import transcribe_audio, is_supported_format, SUPPORTED_AUDIO_FORMATS
from mom_generator import (
    generate_mom_from_transcript, generate_mom_content_text,
    extract_action_items_summary
)
from communication import (
    generate_tts_summary, generate_action_items_audio,
    send_mom_email, is_email_configured
)

# ─── Page Configuration ──────────────────────────────────────────────────────
st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Force consistent light background across Mac/Windows (ignore system dark mode) */
    .stApp, [data-testid="stAppViewContainer"], main {
        background-color: #fafafa !important;
    }
    section[data-testid="stSidebar"] > div {
        background: linear-gradient(180deg, #f8f9ff 0%, #f0f2ff 100%) !important;
    }

    /* Main header */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 { margin: 0; font-size: 1.8rem; }
    .main-header p { margin: 0.3rem 0 0 0; opacity: 0.9; font-size: 0.95rem; }

    /* Cards */
    .info-card {
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .info-card h3 { margin-top: 0; color: #667eea; }

    /* Status badges */
    .badge {
        display: inline-block;
        padding: 0.2em 0.7em;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-scheduled { background: #e3f2fd; color: #1565c0; }
    .badge-completed { background: #e8f5e9; color: #2e7d32; }
    .badge-pending { background: #fff3e0; color: #e65100; }

    /* Chat styling */
    .stChatMessage { border-radius: 12px; }
    
    /* Sidebar styling - ensure text is always visible */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8f9ff 0%, #f0f2ff 100%);
    }
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] .stRadio label {
        color: #31333F !important;
    }
    [data-testid="stSidebar"] [data-testid="stMetricLabel"],
    [data-testid="stSidebar"] [data-testid="stMetricValue"] {
        color: #31333F !important;
    }
    [data-testid="stSidebar"] .stCaption {
        color: #31333F !important;
    }

    /* Action item table */
    .action-table { width: 100%; border-collapse: collapse; }
    .action-table th {
        background: #667eea; color: white; padding: 10px;
        text-align: left;
    }
    .action-table td { padding: 8px; border-bottom: 1px solid #eee; }
    .action-table tr:hover { background: #f5f7ff; }
    
    /* Contact card */
    .contact-card {
        background: white;
        border: 1px solid #e8e8e8;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        transition: box-shadow 0.2s;
    }
    .contact-card:hover { box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
</style>
""", unsafe_allow_html=True)


# ─── Session State Initialization ────────────────────────────────────────────

def init_session_state():
    """Initialize all session state variables."""
    defaults = {
        "messages": [],
        "address_book": None,
        "calendar_service": None,
        "meeting_store": None,
        "mom_store": None,
        "meeting_manager": None,
        "current_page": "Chat",
        "nav_radio": "Chat",  # keep in sync with sidebar radio for routing
        "calendar_mode": "mock",  # "mock" or "google"
        "voice_input_enabled": True,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Initialize service objects
    if st.session_state.address_book is None:
        st.session_state.address_book = AddressBook()

    if st.session_state.meeting_store is None:
        st.session_state.meeting_store = MeetingStore()

    if st.session_state.mom_store is None:
        st.session_state.mom_store = MoMStore()

    if st.session_state.calendar_service is None:
        _init_calendar_service()

    if st.session_state.meeting_manager is None:
        st.session_state.meeting_manager = MeetingManager(
            address_book=st.session_state.address_book,
            calendar_service=st.session_state.calendar_service,
            meeting_store=st.session_state.meeting_store,
        )


def _init_calendar_service():
    """Initialize calendar service (Google or Mock)."""
    if st.session_state.calendar_mode == "google" and GOOGLE_CREDENTIALS_FILE.exists():
        cal = CalendarService()
        if cal.authenticate():
            st.session_state.calendar_service = cal
            return
    # Fall back to mock
    st.session_state.calendar_service = MockCalendarService()
    st.session_state.calendar_mode = "mock"


init_session_state()

# Sync debug logging from Settings checkbox so it applies on all pages (not only when Settings is open)
if "debug_logging_checkbox" in st.session_state:
    config_module.DEBUG_LOGGING = st.session_state["debug_logging_checkbox"]

# ─── Handle programmatic page switches (must run before widgets render) ──────
if st.session_state.get("_goto_page"):
    _target = st.session_state.pop("_goto_page")
    st.session_state["nav_radio"] = _target


# ─── Sidebar ─────────────────────────────────────────────────────────────────

def render_sidebar():
    """Render the sidebar with navigation and tools."""
    with st.sidebar:
        st.markdown(f"## {APP_ICON} {APP_TITLE}")
        st.markdown("---")

        # Navigation - use nav_radio as single source of truth so routing always matches selection
        nav_pages = ["Chat", "Address Book", "Meetings", "MoM Archive", "Settings"]
        page = st.radio(
            "Navigate",
            nav_pages,
            key="nav_radio",
        )
        st.session_state.current_page = page
        # Force rerun when user changes selection so main content updates (fixes sidebar nav on some browsers)
        _nav_prev = st.session_state.get("_nav_prev")
        if _nav_prev is not None and _nav_prev != page:
            st.session_state["_nav_prev"] = page
            st.rerun()
        st.session_state["_nav_prev"] = page

        st.markdown("---")

        # Quick Stats
        st.markdown("### Quick Stats")
        ab = st.session_state.address_book
        ms = st.session_state.meeting_store
        mom_s = st.session_state.mom_store

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Contacts", len(ab.contacts))
            st.metric("MoMs", len(mom_s.get_all_moms()))
        with col2:
            st.metric("Meetings", len(ms.meetings))
            cal_status = "Google" if st.session_state.calendar_mode == "google" else "Local"
            st.metric("Calendar", cal_status)

        st.markdown("---")

        # Calendar mode toggle
        cal_mode = st.selectbox(
            "Calendar Mode",
            ["Mock (Local)", "Google Calendar"],
            index=0 if st.session_state.calendar_mode == "mock" else 1,
        )
        if cal_mode == "Google Calendar" and st.session_state.calendar_mode == "mock":
            st.session_state.calendar_mode = "google"
            _init_calendar_service()
            _reinit_meeting_manager()
        elif cal_mode == "Mock (Local)" and st.session_state.calendar_mode == "google":
            st.session_state.calendar_mode = "mock"
            _init_calendar_service()
            _reinit_meeting_manager()

        st.markdown("---")
        st.caption("Built with Streamlit & OpenAI")


def _reinit_meeting_manager():
    """Reinitialize meeting manager with current services."""
    st.session_state.meeting_manager = MeetingManager(
        address_book=st.session_state.address_book,
        calendar_service=st.session_state.calendar_service,
        meeting_store=st.session_state.meeting_store,
    )


# ─── Chat Page ───────────────────────────────────────────────────────────────

def render_chat_page():
    """Render the main chat interface."""
    st.markdown("""
    <div class="main-header">
        <h1>Smart Office Assistant</h1>
        <p>Schedule meetings, manage contacts, transcribe recordings, and generate meeting minutes - all through natural conversation.</p>
    </div>
    """, unsafe_allow_html=True)

    # Quick action buttons
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        if st.button("📅 Schedule Meeting", use_container_width=True):
            _add_user_message("I want to schedule a meeting")
    with col2:
        if st.button("📋 List Meetings", use_container_width=True):
            _add_user_message("Show my meetings")
    with col3:
        if st.button("🎙️ Upload Recording", use_container_width=True):
            st.session_state["_goto_page"] = "Meetings"
            st.rerun()
    with col4:
        if st.button("📑 Search MoMs", use_container_width=True):
            st.session_state["_goto_page"] = "MoM Archive"
            st.rerun()
    with col5:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state["_confirm_clear_chat"] = True

    # Clear chat confirmation
    if st.session_state.get("_confirm_clear_chat"):
        st.warning("Are you sure you want to clear the entire chat and reset the conversation context?")
        cc1, cc2, cc3 = st.columns([1, 1, 4])
        with cc1:
            if st.button("Yes, clear everything", key="confirm_clear"):
                st.session_state.messages = []
                st.session_state.meeting_manager.reset()
                st.session_state.meeting_manager.conversation_history = []
                st.session_state["_confirm_clear_chat"] = False
                st.rerun()
        with cc2:
            if st.button("No, keep it", key="cancel_clear"):
                st.session_state["_confirm_clear_chat"] = False
                st.rerun()

    st.markdown("---")

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ─── Voice Input (inline in chat area) ────────────────────────────
    _voice_error = None
    try:
        from audio_recorder_streamlit import audio_recorder

        # Place voice recorder in a compact row above the text input
        voice_col1, voice_col2 = st.columns([1, 8])
        with voice_col1:
            audio_bytes = audio_recorder(
                text="",
                recording_color="#e74c3c",
                neutral_color="#667eea",
                icon_size="2x",
                pause_threshold=2.5,
                key="voice_recorder",
            )
        with voice_col2:
            st.caption("Click the microphone to speak your command, or type below.")

        # Process voice if new audio was captured
        if audio_bytes:
            # Use a hash to avoid re-processing the same audio on rerun
            audio_hash = hash(audio_bytes)
            if st.session_state.get("_last_audio_hash") != audio_hash:
                st.session_state["_last_audio_hash"] = audio_hash
                with st.spinner("Transcribing your voice..."):
                    voice_text = _transcribe_voice_input(audio_bytes)
                if voice_text:
                    st.session_state["_pending_voice_text"] = voice_text
                    st.rerun()

        # If there's a pending voice transcription, process it
        if st.session_state.get("_pending_voice_text"):
            voice_text = st.session_state.pop("_pending_voice_text")
            _process_chat_input(voice_text)

    except Exception as e:
        _voice_error = str(e)
        st.caption(f"Voice input unavailable: {_voice_error}")

    # ─── Text Input ───────────────────────────────────────────────────
    user_input = st.chat_input("Type your message... (e.g., 'Schedule a meeting with John next Tuesday at 2pm')")
    if user_input:
        _process_chat_input(user_input)


def _add_user_message(text: str):
    """Add a user message and process it."""
    st.session_state.messages.append({"role": "user", "content": text})
    _process_chat_input(text, already_added=True)


def _process_chat_input(text: str, already_added: bool = False):
    """Process a chat input through the meeting manager."""
    if not already_added:
        st.session_state.messages.append({"role": "user", "content": text})

    with st.chat_message("user"):
        st.markdown(text)

    # Process through meeting manager
    manager = st.session_state.meeting_manager
    result = manager.process_message(text)
    response = result.get("message", "")

    if response:
        st.session_state.messages.append({"role": "assistant", "content": response})
        with st.chat_message("assistant"):
            st.markdown(response)

    st.rerun()


def _transcribe_voice_input(audio_bytes: bytes) -> str:
    """Transcribe voice input bytes using Whisper."""
    try:
        result = transcribe_audio(audio_bytes, "recording.wav")
        if result.get("success"):
            return result["transcript"]
    except Exception as e:
        st.error(f"Voice transcription error: {e}")
    return ""


# ─── Address Book Page ───────────────────────────────────────────────────────

def render_address_book_page():
    """Render the address book management page."""
    st.markdown("""
    <div class="main-header">
        <h1>Address Book</h1>
        <p>Manage your contacts, departments, and organizational directory.</p>
    </div>
    """, unsafe_allow_html=True)

    ab = st.session_state.address_book
    tab1, tab2, tab3 = st.tabs(["All Contacts", "By Department", "Add Contact"])

    with tab1:
        _render_contacts_list(ab)

    with tab2:
        _render_departments(ab)

    with tab3:
        _render_add_contact_form(ab)


def _render_contacts_list(ab: AddressBook):
    """Render searchable contacts list."""
    search = st.text_input("Search contacts...", key="contact_search")

    contacts = ab.search(search) if search else ab.contacts

    if not contacts:
        st.info("No contacts found.")
        return

    for contact in contacts:
        with st.expander(f"**{contact['name']}** - {contact.get('role', '')} | {contact.get('department', '')}"):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Email:** {contact.get('email', 'N/A')}")
                st.write(f"**Phone:** {contact.get('phone', 'N/A')}")
            with col2:
                st.write(f"**Department:** {contact.get('department', 'N/A')}")
                st.write(f"**Role:** {contact.get('role', 'N/A')}")

            # Edit and delete
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button(f"Edit", key=f"edit_{contact['id']}"):
                    st.session_state[f"editing_{contact['id']}"] = True

            with col_b:
                if st.button(f"Delete", key=f"del_{contact['id']}"):
                    ab.delete_contact(contact["id"])
                    st.success(f"Deleted {contact['name']}")
                    st.rerun()

            # Inline edit form
            if st.session_state.get(f"editing_{contact['id']}"):
                with st.form(key=f"edit_form_{contact['id']}"):
                    new_name = st.text_input("Name", value=contact["name"])
                    new_email = st.text_input("Email", value=contact.get("email", ""))
                    new_dept = st.text_input("Department", value=contact.get("department", ""))
                    new_role = st.text_input("Role", value=contact.get("role", ""))
                    new_phone = st.text_input("Phone", value=contact.get("phone", ""))

                    if st.form_submit_button("Save Changes"):
                        ab.update_contact(
                            contact["id"],
                            name=new_name, email=new_email,
                            department=new_dept, role=new_role, phone=new_phone
                        )
                        st.session_state[f"editing_{contact['id']}"] = False
                        st.success("Contact updated!")
                        st.rerun()


def _render_departments(ab: AddressBook):
    """Render contacts grouped by department."""
    departments = ab.get_departments()

    if not departments:
        st.info("No departments found.")
        return

    for dept in departments:
        members = ab.get_department_members(dept)
        with st.expander(f"**{dept}** ({len(members)} members)"):
            for m in members:
                st.markdown(f"- **{m['name']}** - {m.get('role', '')} ({m.get('email', '')})")


def _render_add_contact_form(ab: AddressBook):
    """Render form to add a new contact."""
    with st.form("add_contact_form", clear_on_submit=True):
        st.subheader("Add New Contact")
        name = st.text_input("Full Name *")
        email = st.text_input("Email *")
        department = st.text_input("Department")
        role = st.text_input("Role")
        phone = st.text_input("Phone")

        if st.form_submit_button("Add Contact"):
            if name and email:
                ab.add_contact(name, email, department, role, phone)
                st.success(f"Added {name} to address book!")
                st.rerun()
            else:
                st.error("Name and Email are required.")


# ─── Meetings Page ───────────────────────────────────────────────────────────

def render_meetings_page():
    """Render the meetings management page."""
    st.markdown("""
    <div class="main-header">
        <h1>Meeting History</h1>
        <p>View, search, and track all your scheduled meetings and threads. Upload recordings against specific meetings.</p>
    </div>
    """, unsafe_allow_html=True)

    ms = st.session_state.meeting_store

    tab1, tab2 = st.tabs(["All Meetings", "Meeting Threads"])

    with tab1:
        search = st.text_input("Search meetings...", key="meeting_search")
        meetings = ms.search_meetings(search) if search else ms.get_recent_meetings(20)

        if not meetings:
            st.info("No meetings found. Start by scheduling one in the Chat!")
            return

        for m in meetings:
            status_emoji = {"scheduled": "📅", "completed": "✅", "cancelled": "❌"}.get(
                m.get("status", "scheduled"), "📅"
            )
            with st.expander(
                f"{status_emoji} **{m['title']}** - {m.get('date', '')} at {m.get('time', '')}"
            ):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Date:** {m.get('date', 'N/A')}")
                    st.write(f"**Time:** {m.get('time', 'N/A')}")
                    st.write(f"**Duration:** {m.get('duration_minutes', 45)} minutes")
                with col2:
                    st.write(f"**Status:** {m.get('status', 'scheduled').title()}")
                    st.write(f"**Thread ID:** {m.get('thread_id', 'N/A')}")
                    if m.get("calendar_event_link"):
                        st.markdown(f"[Open in Calendar]({m['calendar_event_link']})")

                if m.get("participants"):
                    st.write(f"**Participants:** {', '.join(m['participants'])}")

                if m.get("description"):
                    st.write(f"**Description:** {m['description']}")

                # ── Cancel / Delete actions ──
                if m.get("status") != "cancelled":
                    act_col1, act_col2, act_col3 = st.columns([1, 1, 4])
                    with act_col1:
                        if st.button("Cancel Meeting", key=f"cancel_{m['id']}"):
                            ms.cancel_meeting(m["id"])
                            st.success(f"Meeting **{m['title']}** has been cancelled.")
                            st.rerun()
                    with act_col2:
                        if st.button("Delete Meeting", key=f"delete_{m['id']}"):
                            st.session_state[f"confirm_del_{m['id']}"] = True

                    # Confirmation for delete
                    if st.session_state.get(f"confirm_del_{m['id']}"):
                        st.warning("Are you sure you want to permanently delete this meeting?")
                        dc1, dc2, dc3 = st.columns([1, 1, 4])
                        with dc1:
                            if st.button("Yes, delete", key=f"yes_del_{m['id']}"):
                                ms.delete_meeting(m["id"])
                                st.session_state[f"confirm_del_{m['id']}"] = False
                                st.success("Meeting deleted.")
                                st.rerun()
                        with dc2:
                            if st.button("No, keep it", key=f"no_del_{m['id']}"):
                                st.session_state[f"confirm_del_{m['id']}"] = False
                                st.rerun()
                else:
                    act_col1, act_col2 = st.columns([1, 5])
                    with act_col1:
                        if st.button("Delete Meeting", key=f"delete_{m['id']}"):
                            st.session_state[f"confirm_del_{m['id']}"] = True

                    if st.session_state.get(f"confirm_del_{m['id']}"):
                        st.warning("Are you sure you want to permanently delete this meeting?")
                        dc1, dc2, dc3 = st.columns([1, 1, 4])
                        with dc1:
                            if st.button("Yes, delete", key=f"yes_del_{m['id']}"):
                                ms.delete_meeting(m["id"])
                                st.session_state[f"confirm_del_{m['id']}"] = False
                                st.success("Meeting deleted.")
                                st.rerun()
                        with dc2:
                            if st.button("No, keep it", key=f"no_del_{m['id']}"):
                                st.session_state[f"confirm_del_{m['id']}"] = False
                                st.rerun()

                st.markdown("---")

                # ── MoM section: either show existing or allow upload ──
                if m.get("mom_id"):
                    _render_meeting_mom_view(m)
                else:
                    _render_meeting_upload_section(m)

    with tab2:
        threads = ms.data.get("threads", {})
        if not threads:
            st.info("No meeting threads yet.")
            return

        for thread_id, meeting_ids in threads.items():
            thread_meetings = ms.get_thread_meetings(thread_id)
            if thread_meetings:
                first_title = thread_meetings[0].get("title", "Untitled Thread")
                with st.expander(f"Thread: {first_title} ({len(thread_meetings)} meetings)"):
                    for i, tm in enumerate(thread_meetings):
                        prefix = "└─" if i == len(thread_meetings) - 1 else "├─"
                        st.markdown(
                            f"{prefix} **{tm['title']}** - {tm.get('date', '')} "
                            f"at {tm.get('time', '')} ({tm.get('status', 'scheduled')})"
                        )


def _render_meeting_mom_view(meeting: dict):
    """Show existing MoM linked to this meeting, with actions."""
    mom_store = st.session_state.mom_store
    mom_data = mom_store.get_mom(meeting["mom_id"])
    mid = meeting["id"]

    if not mom_data:
        st.warning("Linked MoM not found.")
        return

    st.success("Minutes of Meeting available for this meeting.")

    # Inline MoM display toggle
    if st.button("Show / Hide MoM", key=f"toggle_mom_{mid}"):
        st.session_state[f"show_mom_{mid}"] = not st.session_state.get(f"show_mom_{mid}", False)

    if st.session_state.get(f"show_mom_{mid}", False):
        formatted = mom_store.get_mom_formatted(meeting["mom_id"])
        if formatted:
            st.markdown(formatted)

    # Action row
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Generate Audio Summary", key=f"mtg_audio_{mid}"):
            with st.spinner("Generating audio summary..."):
                result = generate_action_items_audio(
                    mom_data.get("action_items", []),
                    mom_data.get("title", "")
                )
                if result.get("success"):
                    st.audio(result["filepath"])
                    st.success("Audio summary generated!")
                else:
                    st.error(result.get("error", "Failed"))

    with col2:
        mom_text = generate_mom_content_text(mom_data)
        st.download_button(
            "Download MoM",
            data=mom_text,
            file_name=f"MoM_{meeting['title'].replace(' ','_')}.md",
            mime="text/markdown",
            key=f"mtg_dl_{mid}",
        )

    with col3:
        if is_email_configured():
            if st.button("Email to Attendees", key=f"mtg_email_{mid}"):
                _email_mom_for_meeting(mom_data, meeting)
        else:
            st.caption("Email not configured (see Settings)")


def _render_meeting_upload_section(meeting: dict):
    """Render the recording upload & transcription section inside a meeting."""
    mid = meeting["id"]
    upload_key = f"upload_active_{mid}"

    st.caption("No Minutes of Meeting yet for this meeting.")

    if not st.session_state.get(upload_key, False):
        if st.button("Upload Recording", key=f"btn_upload_{mid}", type="primary"):
            st.session_state[upload_key] = True
            st.rerun()
        return

    # ── Inline upload form ────────────────────────────────────────────
    st.markdown("#### Upload Recording for this Meeting")
    st.info(
        f"Recording will be linked to **{meeting['title']}** "
        f"({meeting.get('date','')}).  "
        f"Participants: {', '.join(meeting.get('participants', []))}"
    )

    uploaded_file = st.file_uploader(
        "Choose audio/video file",
        type=["mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm", "ogg"],
        key=f"file_{mid}",
        help=f"Supported: {', '.join(SUPPORTED_AUDIO_FORMATS)}. Max 25 MB.",
    )

    language = st.selectbox(
        "Language", ["auto", "en", "hi", "es", "fr", "de"],
        key=f"lang_{mid}",
    )

    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        transcribe_btn = st.button(
            "Transcribe Only", key=f"trans_{mid}",
            disabled=uploaded_file is None,
        )
    with col2:
        full_btn = st.button(
            "Transcribe & Generate MoM", key=f"full_{mid}",
            type="primary", disabled=uploaded_file is None,
        )
    with col3:
        if st.button("Cancel", key=f"cancel_upload_{mid}"):
            st.session_state[upload_key] = False
            st.rerun()

    # ── Process ───────────────────────────────────────────────────────
    if uploaded_file and (transcribe_btn or full_btn):
        file_data = uploaded_file.getvalue()
        lang = None if language == "auto" else language

        # Step 1: Transcribe
        with st.spinner("Transcribing recording..."):
            result = transcribe_audio(file_data, uploaded_file.name, language=lang)

        if not result.get("success"):
            st.error(result.get("error", "Transcription failed"))
            return

        transcript = result["transcript"]
        st.success(
            f"Transcription complete! "
            f"Duration: {result.get('duration', 'N/A')}s, "
            f"Language: {result.get('language', 'N/A')}"
        )
        st.text_area("Transcript", transcript, height=200, key=f"transcript_{mid}")

        if transcribe_btn:
            return  # stop here for transcribe-only

        # Step 2: Generate MoM with meeting context auto-populated
        with st.spinner("Generating Minutes of Meeting..."):
            mom_result = generate_mom_from_transcript(
                transcript=transcript,
                meeting_title=meeting.get("title", ""),
                attendees=meeting.get("participants", []),
                meeting_date=meeting.get("date", ""),
            )

        if not mom_result.get("success"):
            st.error(mom_result.get("error", "MoM generation failed"))
            return

        mom_data = mom_result["mom"]

        # Step 3: Save MoM and link to meeting
        mom_store = st.session_state.mom_store
        ms = st.session_state.meeting_store

        mom_id = mom_store.store_mom(mom_data, meeting_id=mid)
        ms.update_meeting(mid, mom_id=mom_id, status="completed")

        st.success("MoM generated and linked to this meeting!")

        # Display the MoM
        formatted = generate_mom_content_text(mom_data)
        st.markdown(formatted)

        # Generate audio summary automatically
        with st.spinner("Generating audio summary of action items..."):
            audio_result = generate_action_items_audio(
                mom_data.get("action_items", []),
                mom_data.get("title", "")
            )
            if audio_result.get("success"):
                st.audio(audio_result["filepath"])

        # Clean up upload state
        st.session_state[upload_key] = False


def _email_mom_for_meeting(mom_data: dict, meeting: dict):
    """Send MoM email for a specific meeting, resolving emails from participants."""
    ab = st.session_state.address_book
    email_list = []
    # Use participant names from the meeting record to look up emails
    for name in meeting.get("participants", []):
        contacts = ab.find_by_name(name)
        for c in contacts:
            if c.get("email") and c["email"] not in email_list:
                email_list.append(c["email"])

    if not email_list:
        st.warning("No email addresses found for the meeting participants.")
        return

    with st.spinner(f"Sending MoM to {len(email_list)} attendee(s)..."):
        result = send_mom_email(email_list, mom_data)
        if result.get("success"):
            st.success(f"Email sent to: {', '.join(email_list)}")
        else:
            st.error(result.get("error", "Failed to send email"))


# ─── MoM Archive Page ────────────────────────────────────────────────────────

def render_mom_archive_page():
    """Render the MoM archive and search page."""
    st.markdown("""
    <div class="main-header">
        <h1>Minutes of Meeting Archive</h1>
        <p>Search and review past meeting minutes, action items, and decisions.</p>
    </div>
    """, unsafe_allow_html=True)

    mom_store = st.session_state.mom_store

    # Search
    search = st.text_input("Search MoMs by title, attendee, or content...", key="mom_search")
    moms = mom_store.search_moms(search) if search else mom_store.get_all_moms()

    if not moms:
        st.info("No Minutes of Meeting found. Upload a recording or generate MoMs from the Chat.")
        return

    # Check if a specific MoM was selected
    selected = st.session_state.get("selected_mom", None)

    for entry in moms:
        is_selected = selected == entry["id"]
        with st.expander(
            f"**{entry['title']}** - {entry.get('date', '')} "
            f"({entry.get('action_item_count', 0)} action items)",
            expanded=is_selected
        ):
            mom_data = mom_store.get_mom(entry["id"])
            if mom_data:
                # Display formatted MoM
                formatted = mom_store.get_mom_formatted(entry["id"])
                if formatted:
                    st.markdown(formatted)

                st.markdown("---")

                # Action buttons
                col1, col2, col3 = st.columns(3)

                with col1:
                    # Generate audio summary
                    if st.button("Generate Audio Summary", key=f"audio_{entry['id']}"):
                        with st.spinner("Generating audio summary..."):
                            summary_text = extract_action_items_summary(mom_data)
                            result = generate_action_items_audio(
                                mom_data.get("action_items", []),
                                mom_data.get("title", "")
                            )
                            if result.get("success"):
                                st.audio(result["filepath"])
                                st.success("Audio summary generated!")
                            else:
                                st.error(result.get("error", "Failed to generate audio"))

                with col2:
                    # Download MoM
                    mom_text = generate_mom_content_text(mom_data)
                    st.download_button(
                        "Download as Text",
                        data=mom_text,
                        file_name=f"MoM_{entry['id']}.md",
                        mime="text/markdown",
                        key=f"download_{entry['id']}"
                    )

                with col3:
                    # Email MoM
                    if is_email_configured():
                        if st.button("Email to Attendees", key=f"email_{entry['id']}"):
                            with st.spinner("Sending email..."):
                                emails = mom_data.get("attendees", [])
                                # Look up emails from address book
                                ab = st.session_state.address_book
                                email_list = []
                                for name in emails:
                                    contacts = ab.find_by_name(name)
                                    for c in contacts:
                                        if c.get("email"):
                                            email_list.append(c["email"])
                                if email_list:
                                    result = send_mom_email(email_list, mom_data)
                                    if result.get("success"):
                                        st.success("Email sent!")
                                    else:
                                        st.error(result.get("error", "Failed"))
                                else:
                                    st.warning("No email addresses found for attendees.")
                    else:
                        st.info("Configure email in Settings to send MoMs.")

    # Clear selected MoM
    if selected:
        st.session_state.selected_mom = None


# ─── Settings Page ───────────────────────────────────────────────────────────

def render_settings_page():
    """Render the settings page."""
    st.markdown("""
    <div class="main-header">
        <h1>Settings</h1>
        <p>Configure Google Calendar, email, and other preferences.</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["Google Calendar", "Email", "About", "Debug"])

    with tab1:
        st.subheader("Google Calendar Integration")

        if GOOGLE_CREDENTIALS_FILE.exists():
            st.success(f"Credentials found: `{GOOGLE_CREDENTIALS_FILE.name}`")

            if st.session_state.calendar_mode == "google":
                st.success("Connected to Google Calendar")
            else:
                st.info("Currently using Mock (Local) calendar mode.")
                if st.button("Connect to Google Calendar"):
                    st.session_state.calendar_mode = "google"
                    _init_calendar_service()
                    _reinit_meeting_manager()
                    st.rerun()
        else:
            st.warning("Google Calendar credentials not found.")
            st.markdown("""
            ### Setup Instructions
            
            1. Go to [Google Cloud Console](https://console.cloud.google.com/)
            2. Create a new project (or select existing)
            3. Enable the **Google Calendar API**
            4. Go to **Credentials** > **Create Credentials** > **OAuth 2.0 Client ID**
            5. Select **Desktop Application** as the application type
            6. Download the credentials JSON file
            7. Place the file in the credentials folder (as `credentials.json` or keep the default `client_secret_*.json` name):
            """)
            st.code(str(GOOGLE_CREDENTIALS_FILE.parent))
            st.markdown("""
            8. Restart the application and click **Connect to Google Calendar**
            
            > **Note:** The first connection will open a browser window for OAuth authorization.
            """)

        st.markdown("---")
        st.subheader("Calendar Mode")
        st.write(f"**Current mode:** {'Google Calendar' if st.session_state.calendar_mode == 'google' else 'Mock (Local)'}")
        st.info(
            "**Mock mode** simulates calendar operations locally. Meetings are recorded but "
            "no actual Google Calendar events are created. Great for testing!"
        )

    with tab2:
        st.subheader("Email Configuration (SMTP)")

        if is_email_configured():
            st.success("Email is configured.")
        else:
            st.warning("Email is not configured.")
            st.markdown("""
            Add these to your `.env` file to enable email:
            """)
            st.code("""
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your.email@gmail.com
SMTP_PASSWORD=your_app_specific_password
            """)
            st.markdown("""
            > **For Gmail:** You need to use an [App Password](https://myaccount.google.com/apppasswords) 
            > instead of your regular password.
            """)

    with tab4:
        st.subheader("Debug logging")
        debug_enabled = st.checkbox(
            "Print debug messages to the terminal",
            value=DEBUG_LOGGING,
            key="debug_logging_checkbox",
            help="When enabled, debug output (e.g. OpenAI requests/responses, or any debug_log() calls) is printed in the terminal where you run the app.",
        )
        config_module.DEBUG_LOGGING = debug_enabled
        if debug_enabled:
            st.info("Debug logging is **on**. Check the terminal/console where Streamlit is running.")
        else:
            st.caption("You can also set `DEBUG_LOGGING=true` in your `.env` file to enable on startup.")

    with tab3:
        st.subheader("About Smart Office Assistant")
        st.markdown("""
        **Smart Office Assistant** is an intelligent web-based assistant that streamlines 
        meeting management through natural language interaction.
        
        ### Features
        - **Natural Language Meeting Scheduling** - Schedule meetings using conversational commands
        - **Address Book Management** - Maintain contacts with departments and roles
        - **Google Calendar Integration** - Create events with automatic invites
        - **Meeting Thread Tracking** - Link follow-up meetings with predecessors
        - **Audio/Video Transcription** - Transcribe recordings using OpenAI Whisper
        - **Minutes of Meeting Generation** - Auto-generate structured MoMs
        - **Action Item Extraction** - Identify tasks with owners and deadlines
        - **Text-to-Speech Summaries** - Audio summaries of action items
        - **Email MoM Distribution** - Send meeting minutes to attendees
        
        ### Technologies
        - **Streamlit** - Web framework
        - **OpenAI GPT** - NLU and content generation
        - **OpenAI Whisper** - Speech-to-text
        - **OpenAI TTS** - Text-to-speech
        - **Google Calendar API** - Calendar integration
        
        ### Example Commands
        ```
        Schedule a meeting with John next Tuesday at 2pm
        Schedule a meeting with all members of Tech department for Thursday at 11am
        Schedule a meeting with Rohit from Digital Marketing and Puneet from Tech for Monday
        Show my meetings
        ```
        """)


# ─── Page Router ─────────────────────────────────────────────────────────────

PAGE_MAP = {
    "Chat": render_chat_page,
    "Address Book": render_address_book_page,
    "Meetings": render_meetings_page,
    "MoM Archive": render_mom_archive_page,
    "Settings": render_settings_page,
}


def main():
    """Main application entry point."""
    render_sidebar()
    # Use nav_radio (sidebar selection) as source of truth so Address Book / Meetings etc. always load
    current = st.session_state.get("nav_radio") or st.session_state.get("current_page", "Chat")
    page_func = PAGE_MAP.get(current, render_chat_page)
    page_func()


if __name__ == "__main__":
    main()
