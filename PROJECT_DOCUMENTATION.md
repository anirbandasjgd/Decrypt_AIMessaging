# Smart Office Assistant — Project Documentation

**Repository:** [Decrypt_AIMessaging](https://github.com/anirbandasjgd/Decrypt_AIMessaging)  
**Version:** 1.0  
**Last updated:** February 2026

This document summarizes the **flows**, **technical design**, and **summary report** for the Smart Office Assistant (Decrypt AI Capstone) application.

---

## 1. Summary Report

### 1.1 What It Is

The **Smart Office Assistant** is a web-based application that helps users manage meetings, contacts, and meeting documentation through natural language (chat and voice). It supports:

- **Login and multi-user isolation** — Users log in with email/password; Admin sees all data, individual users see only their own meetings, address book, MoMs, and chat history.
- **Natural language meeting scheduling** — e.g. “Schedule a meeting with John next Tuesday at 2pm” or “all members of Tech department Thursday at 11am.”
- **Address book** — Per-user contacts; Admin uses the full organization address book.
- **Meeting documentation** — Upload audio/video, transcribe with Whisper, generate Minutes of Meeting (MoM) with GPT, and email MoMs to attendees.
- **Communication** — Text and voice input in chat; TTS action-item summaries; SMTP email for MoM and meeting-invite notifications.

### 1.2 Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Streamlit 1.30+ |
| **NLU & generation** | OpenAI GPT-4o-mini (function calling) |
| **Speech-to-text** | OpenAI Whisper |
| **Text-to-speech** | OpenAI TTS |
| **Calendar** | Google Calendar API v3 (OAuth 2.0) or Mock |
| **Email** | SMTP (Gmail-compatible) |
| **Persistence** | JSON files (login, address book, meetings, MoMs, chat) |
| **Language** | Python 3.10+ |

### 1.3 Key Deliverables

- **Login** — `data/login.json` with Admin (Admin/Admin) and optional users; session-scoped `user_email` and `is_admin`.
- **Per-user data** — Meetings tagged by `user_email`; address book and MoMs in user-specific paths; chat history per user.
- **Admin capabilities** — Full org address book; view all meetings and all MoMs; own chat.
- **Flows** — Login → Chat (scheduling, list, etc.) → Address Book / Meetings / MoM Archive / Settings, with consistent sidebar and theme.

---

## 2. User Flows

### 2.1 Application Entry and Login

```
User opens app (e.g. http://localhost:8501)
    → If not logged in: Login screen (email, password)
    → On Submit: verify_user() against data/login.json
    → If valid: set session_state (user_email, is_admin), load user-scoped stores, rerun
    → If invalid: show "Invalid email or password"
    → If logged in: Sidebar + main area (Chat / Address Book / Meetings / MoM Archive / Settings)
    → Logout: clears session auth and user-scoped data, returns to login screen
```

**Default admin:** Email `Admin`, password `Admin` (stored in `data/login.json`).

### 2.2 Chat and Meeting Scheduling Flow

```
User types or speaks in Chat
    → Voice: audio_recorder_streamlit → Whisper transcription → text treated as user message
    → Text appended to session_state.messages; persisted to data/chat_{user}.json
    → meeting_manager.process_message(text)
          → NLU: parse_command() → intent + meeting_details / missing_fields
          → If intent switch (e.g. list_meetings) while in scheduling: reset state, handle new intent
          → State machine:
                IDLE → schedule_meeting → COLLECTING_INFO (resolve participants via AddressBook)
                COLLECTING_INFO → missing fields → generate_followup_question(); stay COLLECTING_INFO
                COLLECTING_INFO → all present → AWAITING_CONFIRMATION (show summary)
                AWAITING_CONFIRMATION → confirm → _execute_scheduling(); reset
                AWAITING_CONFIRMATION → cancel/modify → reset or re-collect
                (Also: AWAITING_SLOT_CHOICE, AWAITING_DISAMBIGUATION for first-available and disambiguation)
          → On execute: Calendar (Google or Mock) create_event → MeetingStore.add_meeting (with user_email)
          → Email: send_meeting_invite_notification(SMTP_EMAIL); send_meeting_invite_to_participants(attendee_emails)
    → Response shown in chat and appended to messages; chat saved
```

**Quick actions on Chat page:** Schedule Meeting, List Meetings, Upload Recording (→ Meetings), Search MoMs (→ MoM Archive), Clear Chat (with confirmation).

### 2.3 Address Book Flow

```
User opens "Address Book" in sidebar
    → Address book source: Admin → data/address_book.json (full org); others → data/address_book_{sanitized_email}.json
    → Tabs: All Contacts (search), By Department, Add Contact
    → CRUD: search, add form, edit/delete per contact (persisted to same file)
```

### 2.4 Meetings Page Flow

```
User opens "Meetings"
    → MeetingStore returns only current user’s meetings (or all if Admin)
    → Tabs: All Meetings, Meeting Threads
    → Per meeting: view details; Cancel / Delete (with confirmation); if no MoM → Upload Recording
    → Upload: file picker + Transcribe Only / Transcribe & Generate MoM
          → Whisper → transcript
          → Optional: mom_generator.generate_mom_from_transcript() → MoMStore.store_mom (user-scoped dir)
          → Link MoM to meeting; optional TTS summary and email to attendees
    → If MoM exists: show/hide MoM, Generate Audio Summary, Download MoM, Email to Attendees
```

### 2.5 MoM Archive Flow

```
User opens "MoM Archive"
    → MoMStore: for Admin aggregates all users’ MoM indices; for others only own
    → Search by title/attendee/content
    → Per entry: view formatted MoM; Generate Audio Summary; Download; Email to Attendees (if configured)
```

### 2.6 Settings Flow

```
User opens "Settings"
    → Tabs: Google Calendar (credentials path, connect/mode), Email (SMTP .env guidance), Debug logging, About
    → Calendar mode switch (Mock / Google) reinitializes calendar service and meeting manager
```

---

## 3. Technical Design

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Streamlit UI (app.py)                           │
│  Login → Sidebar (nav, stats, calendar mode, logout) + Page content      │
└─────────────────────────────────────────────────────────────────────────┘
         │
         ├── auth.py              login.json, verify_user
         ├── config.py            paths, env, sanitize_user_for_path
         ├── address_book.py     AddressBook (per-user or org file)
         ├── storage.py          MeetingStore, MoMStore (user-scoped; admin sees all)
         ├── meeting_manager.py  MeetingManager (state machine, calendar, store)
         ├── nlu_engine.py       parse_command, follow-up, confirmation
         ├── calendar_service.py Google Calendar / MockCalendarService
         ├── transcription_service.py Whisper
         ├── mom_generator.py    MoM from transcript (GPT)
         └── communication.py    TTS, send_email, send_mom_email, meeting invites
```

### 3.2 Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| **app.py** | Page config, CSS, login gate, session init, sidebar, Chat/Address Book/Meetings/MoM Archive/Settings pages, chat persist, main router. |
| **auth.py** | Ensure `data/login.json`, load/save, `verify_user(email, password) → (success, is_admin)`. |
| **config.py** | BASE_DIR, DATA_DIR, MOMS_DIR, credentials, OpenAI/SMTP env, `ADDRESS_BOOK_FILE`, `MEETINGS_FILE`, `LOGIN_FILE`, `sanitize_user_for_path`, `get_address_book_path_for_user`, `get_chat_history_path_for_user`. |
| **address_book.py** | AddressBook(filepath \| user_email, is_admin): load/save JSON, CRUD, find_by_name, resolve_participant, get_emails_for_contacts, departments. |
| **storage.py** | MeetingStore(user_email, is_admin): single file, `user_email` on each meeting, filter for non-admin. MoMStore(user_email, is_admin): per-user dir under MOMS_DIR; admin aggregates in get_all_moms. |
| **meeting_manager.py** | MeetingManager(address_book, calendar, meeting_store): process_message(), state machine (IDLE → COLLECTING_INFO → AWAITING_CONFIRMATION, etc.), participant resolution, calendar create, store add, email notifications. |
| **nlu_engine.py** | parse_command(), generate_followup_question(), generate_confirmation_message(), classify_confirmation(); uses OpenAI function calling. |
| **calendar_service.py** | CalendarService (Google OAuth, create_event, availability), MockCalendarService (in-memory). |
| **transcription_service.py** | Whisper API: transcribe_audio(), format/size checks. |
| **mom_generator.py** | generate_mom_from_transcript(), generate_mom_content_text(), extract_action_items_summary(). |
| **communication.py** | TTS (generate_action_items_audio), send_email(), send_mom_email(), send_meeting_invite_notification(), send_meeting_invite_to_participants(). |

### 3.3 Data Layout (Files and Directories)

```
Decrypt_AIMessaging/
├── app.py
├── auth.py
├── config.py
├── address_book.py
├── storage.py
├── meeting_manager.py
├── nlu_engine.py
├── calendar_service.py
├── transcription_service.py
├── mom_generator.py
├── communication.py
├── requirements.txt
├── .streamlit/
│   └── config.toml              # Theme (e.g. base = "light")
├── data/
│   ├── login.json               # users: [{ email, password, role }]
│   ├── address_book.json        # Full org book (used by Admin)
│   ├── address_book_{user}.json # Per-user (ignored in git)
│   ├── chat_{user}.json         # Per-user chat history (ignored in git)
│   ├── meetings.json            # All meetings (each has user_email)
│   └── moms/
│       └── {sanitized_user}/    # Per-user MoM files + index.json
├── credentials/                  # credentials.json, token.json
└── audio_output/                # TTS outputs
```

### 3.4 Session State (app.py)

After login, session state includes:

- **Auth:** `user_email`, `is_admin`
- **Stores:** `address_book`, `meeting_store`, `mom_store`, `meeting_manager`, `calendar_service`
- **UI:** `current_page`, `nav_radio`, `_nav_prev`, `calendar_mode`
- **Chat:** `messages` (loaded/saved per user via `_chat_loaded_for_user`)

Stores are created with `user_email` and `is_admin` so that data is scoped correctly.

### 3.5 Meeting Manager State Machine (Simplified)

```
                    IDLE
                      │ schedule_meeting / followup_meeting
                      ▼
              COLLECTING_INFO ◄────── missing fields (follow-up questions)
                      │ all fields + participants resolved
                      ▼
              AWAITING_CONFIRMATION
                      │ confirm / cancel / modify
                      ▼
              (execute → store + calendar + email) or reset
```

Additional states: **AWAITING_SLOT_CHOICE** (first available slot), **AWAITING_DISAMBIGUATION** (choose among multiple contacts). Intent switch to non-scheduling (e.g. list_meetings) resets to IDLE.

### 3.6 Data Models (Core Fields)

- **login.json user:** `email`, `password`, `role` ("admin" | "user").
- **Contact:** `id`, `name`, `email`, `department`, `role`, `phone`.
- **Meeting record:** `id`, `thread_id`, `parent_meeting_id`, `user_email`, `title`, `date`, `time`, `duration_minutes`, `participants`, `participant_emails`, `description`, `calendar_event_id`, `calendar_event_link`, `mom_id`, `status`, `created_at`.
- **MoM (index entry):** `id`, `meeting_id`, `user_email`, `title`, `date`, `attendees`, `action_item_count`, `created_at`. Full MoM JSON includes `action_items`, `key_discussion_points`, `decisions`, etc.
- **Chat:** `messages`: list of `{ "role": "user"|"assistant", "content": "..." }`.

---

## 4. Data Flows (Summary)

| Flow | Trigger | Path |
|------|---------|------|
| **Login** | Submit login form | auth.verify_user → session_state (user_email, is_admin) → init_session_state (user-scoped stores, load chat) |
| **Scheduling** | Chat message | NLU parse → MeetingManager (state machine) → AddressBook resolve → Calendar create_event → MeetingStore.add_meeting → communication (organizer + participant emails) |
| **List meetings** | Chat "list" or Meetings page | MeetingStore.meetings (filtered by user_email or admin) |
| **MoM from recording** | Meetings page, Upload + Transcribe & Generate MoM | Whisper → transcript → mom_generator → MoMStore (user dir) → link to meeting; optional TTS + email |
| **Chat persistence** | After each assistant reply / clear chat | save_chat_history_for_user(user_email, messages) → data/chat_{user}.json |

---

## 5. Configuration and Run

### 5.1 Environment Variables (.env in parent directory)

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key (GPT, Whisper, TTS) |
| `SMTP_EMAIL` / `SMTP_PASSWORD` | For email | Sender and app password (e.g. Gmail) |
| `DEBUG_LOGGING` | No | true/yes for debug output |

### 5.2 Running the Application

```bash
cd Decrypt_AIMessaging
# Optional: venv
# python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Or from project root:

```bash
/path/to/.venv/bin/python -m streamlit run /path/to/Decrypt_AIMessaging/app.py
```

Default URL: **http://localhost:8501** (or next free port). Login with **Admin** / **Admin** or a user defined in `data/login.json`.

---

## 6. Security and Multi-User Model

- **Credentials:** No secrets in code; `.env` and `credentials/` are gitignored where appropriate.
- **Login:** Passwords stored in `login.json` (plain text); suitable for demo/capstone. Production would use hashing and secure storage.
- **Isolation:** Meetings filtered by `user_email`; MoMs and address book in per-user paths; chat in `chat_{user}.json`. Admin bypasses filters for meetings and MoMs and uses full org address book.
- **Logout:** Clears auth and user-scoped session data and returns to login screen.

---

## 7. References

- **Requirements:** `REQUIREMENTS_DOCUMENT.md` in this repository.
- **Repo:** [https://github.com/anirbandasjgd/Decrypt_AIMessaging](https://github.com/anirbandasjgd/Decrypt_AIMessaging).

---

*End of Project Documentation*
