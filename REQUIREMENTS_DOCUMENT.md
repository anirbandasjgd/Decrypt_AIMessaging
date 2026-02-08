# Smart Office Assistant — Requirements Document

## 1. Project Overview

**Application Name:** Smart Office Assistant
**Type:** Web-based intelligent assistant
**Framework:** Streamlit (Python)
**Purpose:** Streamline meeting management through natural language interaction, automated scheduling, intelligent meeting documentation, and multi-channel communication.

---

## 2. Functional Requirements

### 2.1 Meeting Scheduling & Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1.1 | Accept natural language text commands for scheduling meetings (e.g., "Schedule a meeting with John next Tuesday at 2pm") | Must Have |
| FR-2.1.2 | Parse relative date references: "next Tuesday", "coming Monday", "Thursday after next week" | Must Have |
| FR-2.1.3 | Resolve participant names against the address book, including first-name and full-name matching | Must Have |
| FR-2.1.4 | Support department-level scheduling (e.g., "all members of Tech department") | Must Have |
| FR-2.1.5 | Support multi-person cross-department scheduling (e.g., "Rohit from Digital Marketing and Puneet from Tech") | Must Have |
| FR-2.1.6 | Disambiguate when multiple contacts share a name by asking clarifying questions | Must Have |
| FR-2.1.7 | Detect incomplete meeting specifications and prompt the user for missing information via conversational follow-up (date, time, duration, participants) | Must Have |
| FR-2.1.8 | Support "first available time slot" requests by checking calendar availability | Must Have |
| FR-2.1.9 | Apply a configurable default meeting duration (45 minutes) when unspecified, but prefer to ask the user | Must Have |
| FR-2.1.10 | Present a confirmation summary before creating any calendar event; allow the user to confirm, cancel, or modify | Must Have |
| FR-2.1.11 | Create Google Calendar events with attendee invites and Google Meet conferencing links | Must Have |
| FR-2.1.12 | Support a Mock Calendar mode for local testing without Google API credentials | Must Have |
| FR-2.1.13 | Track meeting threads to link follow-up meetings with their predecessors | Must Have |
| FR-2.1.14 | Cancel scheduled meetings (mark as cancelled, retain record) | Must Have |
| FR-2.1.15 | Delete meetings permanently with confirmation prompt | Must Have |
| FR-2.1.16 | List and search scheduled meetings by title, participants, or description | Must Have |
| FR-2.1.17 | Detect intent switches mid-conversation (e.g., user abandons scheduling to list meetings) and reset context appropriately | Must Have |

### 2.2 Address Book Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.2.1 | Maintain a persistent address book in JSON format with contacts' names, emails, departments, roles, and phone numbers | Must Have |
| FR-2.2.2 | Provide CRUD operations: add, edit, delete contacts via the UI | Must Have |
| FR-2.2.3 | Search contacts by name, email, department, or role | Must Have |
| FR-2.2.4 | View contacts grouped by department | Must Have |
| FR-2.2.5 | Pre-populate the address book with sample contacts across multiple departments (Tech, Digital Marketing, HR, Finance, Sales, Product, Design) | Should Have |
| FR-2.2.6 | Store a "user" profile (the assistant's owner) for calendar identity | Should Have |

### 2.3 Meeting Documentation

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.3.1 | Upload audio/video meeting recordings (mp3, mp4, wav, webm, ogg, m4a, mpeg, mpga) up to 25 MB | Must Have |
| FR-2.3.2 | Transcribe recordings using OpenAI Whisper API with auto-detected or user-specified language | Must Have |
| FR-2.3.3 | Upload recordings in context of a specific meeting (from the Meetings page) so the MoM is automatically linked | Must Have |
| FR-2.3.4 | Auto-populate meeting context (title, date, participants) when generating MoM from a known meeting | Must Have |
| FR-2.3.5 | Generate structured Minutes of Meeting (MoM) from transcripts using GPT with function calling, extracting: title, summary, key discussion points, decisions, and action items | Must Have |
| FR-2.3.6 | Each action item must include: description, assigned owner, deadline, priority (high/medium/low), and status | Must Have |
| FR-2.3.7 | Store MoMs persistently with a searchable index (by title, attendees, content) | Must Have |
| FR-2.3.8 | Display formatted MoM inline within the meeting record | Must Have |
| FR-2.3.9 | Download MoM as a Markdown (.md) file | Must Have |
| FR-2.3.10 | Support "Transcribe Only" mode (transcript without MoM generation) | Should Have |

### 2.4 Communication

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.4.1 | Support text input via a chat interface | Must Have |
| FR-2.4.2 | Support voice input via in-browser microphone recording, transcribed through Whisper | Must Have |
| FR-2.4.3 | Generate text-to-speech (TTS) audio summaries of action items using OpenAI TTS API | Must Have |
| FR-2.4.4 | Play generated audio summaries directly in the browser | Must Have |
| FR-2.4.5 | Send MoM emails to meeting attendees in formatted HTML with an action-items table | Must Have |
| FR-2.4.6 | Attach TTS audio summary file to MoM emails | Should Have |
| FR-2.4.7 | Support SMTP email delivery (Gmail-compatible with app-specific passwords) | Must Have |
| FR-2.4.8 | Gracefully degrade when email or voice dependencies are not configured, showing setup guidance | Must Have |

### 2.5 Chat Interface & User Experience

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.5.1 | Provide a conversational chat interface with message history | Must Have |
| FR-2.5.2 | Quick action buttons: Schedule Meeting, List Meetings, Upload Recording, Search MoMs, Clear Chat | Must Have |
| FR-2.5.3 | Clear Chat action with confirmation prompt; resets all messages, NLU conversation history, and scheduling state | Must Have |
| FR-2.5.4 | Multi-page navigation via sidebar: Chat, Address Book, Meetings, MoM Archive, Settings | Must Have |
| FR-2.5.5 | Display quick stats in sidebar: contact count, meeting count, MoM count, calendar mode | Should Have |
| FR-2.5.6 | Show meeting threads (parent/follow-up chain) in a dedicated tab | Should Have |

---

## 3. Non-Functional Requirements

| ID | Requirement | Category |
|----|-------------|----------|
| NFR-3.1 | All data (address book, meetings, MoMs) must persist across application restarts via JSON file storage | Persistence |
| NFR-3.2 | OpenAI API calls must use low temperature (0.1–0.2) for NLU and MoM extraction to ensure deterministic outputs | Reliability |
| NFR-3.3 | Audio files must be validated for format and size before API submission | Validation |
| NFR-3.4 | Google Calendar OAuth tokens must be cached locally to avoid re-authentication on every run | Usability |
| NFR-3.5 | The application must run without Google Calendar credentials (Mock mode) for development and testing | Testability |
| NFR-3.6 | Sensitive credentials (API keys, SMTP passwords) must be loaded from environment variables / `.env` file, never hardcoded | Security |
| NFR-3.7 | All UI pages must render with consistent styling (gradient headers, card layouts, responsive columns) | UX |
| NFR-3.8 | Error states from API calls must surface user-friendly messages, not raw tracebacks | Robustness |

---

## 4. System Architecture

### 4.1 Module Overview

```
smart_office_assistant/
├── app.py                    # Main Streamlit application (UI, routing, page rendering)
├── config.py                 # Configuration & environment variable loading
├── nlu_engine.py             # NLU: intent classification & entity extraction via OpenAI
├── address_book.py           # Contact management (CRUD, search, department queries)
├── calendar_service.py       # Google Calendar API + Mock calendar for testing
├── meeting_manager.py        # Multi-turn scheduling orchestration & state machine
├── transcription_service.py  # Audio/video transcription via OpenAI Whisper
├── mom_generator.py          # MoM generation & action item extraction via GPT
├── communication.py          # TTS generation (OpenAI) & email delivery (SMTP)
├── storage.py                # Persistent storage for meetings & MoMs (JSON)
├── requirements.txt          # Python dependencies
├── data/
│   ├── address_book.json     # Contact database (15 pre-loaded contacts)
│   ├── meetings.json         # Meeting records & thread mapping
│   └── moms/                 # Individual MoM JSON files + index
│       └── index.json
├── credentials/              # Google OAuth credentials & token
│   └── credentials.json
└── audio_output/             # Generated TTS audio files
```

### 4.2 Key Data Flows

**Meeting Scheduling Flow:**
```
User Input (text/voice)
  → NLU Engine (intent classification + entity extraction)
    → Meeting Manager (state machine)
      → Address Book (participant resolution)
      → [If incomplete] Follow-up questions ← User responses
      → [If "first available"] Calendar Service (availability check)
      → Confirmation prompt ← User confirms
      → Calendar Service (create event + send invites)
      → Meeting Store (persist record with thread tracking)
```

**Meeting Documentation Flow:**
```
Audio/Video Upload (from Meetings page, linked to a specific meeting)
  → Transcription Service (OpenAI Whisper)
    → MoM Generator (GPT function calling)
      → MoM Store (persist with meeting linkage)
      → TTS Service (action items audio summary)
      → Email Service (send to attendees with audio attachment)
```

### 4.3 Conversation State Machine

```
                 ┌──────────────────────────────────────┐
                 │              IDLE                     │
                 └──────┬────────────┬──────────────────┘
       schedule intent  │            │  other intents
                        ▼            ▼
              ┌─────────────┐   (handled directly)
              │ COLLECTING   │
              │ _INFO        │◄── missing fields
              └──────┬──────┘
                     │ all fields present
                     ▼
              ┌──────────────────┐
              │ AWAITING         │
              │ _CONFIRMATION    │
              └──┬──────┬───────┘
        confirm  │      │ cancel/modify
                 ▼      ▼
          (execute)  (reset / re-collect)
```

Additional states: `AWAITING_SLOT_CHOICE` (user picks a time slot), `AWAITING_DISAMBIGUATION` (user clarifies ambiguous participant name).

Intent switches (e.g., "list meetings" while mid-scheduling) are detected and reset the state machine to `IDLE`.

---

## 5. External API Dependencies

| API | Purpose | Authentication | Module |
|-----|---------|----------------|--------|
| **OpenAI Chat Completions** (gpt-4o-mini) | NLU parsing, MoM generation, follow-up question generation, confirmation classification | API key | `nlu_engine.py`, `mom_generator.py` |
| **OpenAI Whisper** (whisper-1) | Audio/video transcription | API key | `transcription_service.py` |
| **OpenAI TTS** (tts-1) | Text-to-speech audio summaries | API key | `communication.py` |
| **Google Calendar API v3** | Event creation, availability checking, event listing | OAuth 2.0 | `calendar_service.py` |
| **SMTP** (Gmail) | Email delivery of MoM documents | App password | `communication.py` |

---

## 6. Data Models

### 6.1 Contact
```json
{
  "id": "c001",
  "name": "Rohit Sharma",
  "email": "rohit.sharma@company.com",
  "department": "Digital Marketing",
  "role": "Marketing Manager",
  "phone": "+91-9876543210"
}
```

### 6.2 Meeting Record
```json
{
  "id": "mtg_abc1234567",
  "thread_id": "thread_12345678",
  "parent_meeting_id": null,
  "title": "Sprint Planning",
  "date": "2026-02-12",
  "time": "14:00",
  "duration_minutes": 45,
  "participants": ["John Mathew", "Priya Nair"],
  "participant_emails": ["john.mathew@company.com", "priya.nair@company.com"],
  "description": "",
  "calendar_event_id": "google_event_id_here",
  "calendar_event_link": "https://calendar.google.com/...",
  "mom_id": null,
  "status": "scheduled",
  "created_at": "2026-02-07T12:00:00"
}
```

### 6.3 Minutes of Meeting
```json
{
  "id": "mom_abc1234567",
  "meeting_id": "mtg_abc1234567",
  "title": "Sprint Planning",
  "date": "2026-02-12",
  "attendees": ["John Mathew", "Priya Nair"],
  "summary": "Discussed sprint goals and task assignments.",
  "key_discussion_points": ["Backend API refactoring", "UI redesign timeline"],
  "decisions": ["Move deadline to Feb 20"],
  "action_items": [
    {
      "description": "Complete API refactoring",
      "owner": "John Mathew",
      "deadline": "2026-02-18",
      "priority": "high",
      "status": "Pending"
    }
  ],
  "transcript": "Full transcript text...",
  "audio_summary_path": "audio_output/action_items_20260212.mp3",
  "created_at": "2026-02-12T15:30:00"
}
```

### 6.4 NLU Parsed Command
```json
{
  "intent": "schedule_meeting",
  "meeting_details": {
    "title": "Sprint Planning",
    "participants": [
      {"name": "John", "department": "", "is_department_group": false},
      {"name": "Tech", "department": "Tech", "is_department_group": true}
    ],
    "date": "2026-02-12",
    "time": "14:00",
    "duration_minutes": 45,
    "use_first_available": false,
    "is_followup": false
  },
  "missing_fields": [],
  "response_message": ""
}
```

---

## 7. Configuration & Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key for GPT, Whisper, TTS |
| `OPENAI_ORG_ID` | No | — | OpenAI organization ID |
| `NLU_MODEL` | No | `gpt-4o-mini` | Model for NLU parsing |
| `CHAT_MODEL` | No | `gpt-4o-mini` | Model for general chat |
| `MOM_MODEL` | No | `gpt-4o-mini` | Model for MoM generation |
| `SMTP_SERVER` | No | `smtp.gmail.com` | SMTP server for email |
| `SMTP_PORT` | No | `587` | SMTP port |
| `SMTP_EMAIL` | No | — | Sender email address |
| `SMTP_PASSWORD` | No | — | SMTP password (app-specific for Gmail) |

**Application Constants (in `config.py`):**
- Default meeting duration: 45 minutes
- Working hours: 9 AM – 6 PM
- Slot increment: 30 minutes
- Max audio file size: 25 MB
- TTS model: `tts-1`, voice: `alloy`
- Whisper model: `whisper-1`

---

## 8. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Streamlit 1.30+ |
| **AI / NLU** | OpenAI GPT-4o-mini (function calling) |
| **Speech-to-Text** | OpenAI Whisper API |
| **Text-to-Speech** | OpenAI TTS API |
| **Calendar** | Google Calendar API v3 (OAuth 2.0) |
| **Email** | Python smtplib (SMTP/TLS) |
| **Voice Input** | audio-recorder-streamlit (browser WebRTC) |
| **Data Storage** | JSON files (address book, meetings, MoMs) |
| **Language** | Python 3.11+ |

---

## 9. Test Scenarios

### 9.1 Standard Scheduling
| # | Input | Expected Behaviour |
|---|-------|--------------------|
| 1 | "Schedule a meeting with John next Tuesday at 2pm" | Resolves John Mathew, parses date/time, confirms, creates event |
| 2 | "Schedule a meeting with Priya for 30 minutes tomorrow at 10am" | Resolves Priya Nair, 30-min duration, creates event |

### 9.2 Complex Scheduling
| # | Input | Expected Behaviour |
|---|-------|--------------------|
| 3 | "Schedule a meeting with all members of Tech department for Thursday after next week at 11am" | Resolves all Tech contacts (John, Puneet, Priya, Amit, Suresh), parses "Thursday after next week", confirms with 5 attendees |
| 4 | "Schedule a meeting with Rohit from Digital Marketing and Puneet from Tech departments for the coming week Monday, schedule it for the first available time-slot on my calendar" | Resolves Rohit (DM) and Puneet (Tech), finds first available slot on next Monday, confirms |

### 9.3 Incomplete Specifications
| # | Input | Expected Behaviour |
|---|-------|--------------------|
| 5 | "Schedule a meeting with Rohit next week Monday" | Detects missing time and duration; asks follow-up questions |
| 6 | "Schedule a meeting at 3pm next week" | Detects missing day (which day next week?) and participants; asks follow-up |
| 7 | "Schedule a meeting with Vikram" | Detects missing date, time, duration; asks follow-up |

### 9.4 Disambiguation
| # | Input | Expected Behaviour |
|---|-------|--------------------|
| 8 | "Schedule a meeting with Sneha" | Resolves to Sneha Reddy (unique); no disambiguation needed |
| 9 | Two contacts named "Amit" exist in different departments | Presents both options, asks user to specify |

### 9.5 Meeting Management
| # | Action | Expected Behaviour |
|---|--------|--------------------|
| 10 | Cancel a scheduled meeting | Status changes to "cancelled", record retained |
| 11 | Delete a meeting | Confirmation prompt; permanent removal from records and threads |
| 12 | Clear chat | Confirmation prompt; clears messages, resets scheduling state |

### 9.6 Meeting Documentation
| # | Action | Expected Behaviour |
|---|--------|--------------------|
| 13 | Upload recording against a meeting and click "Transcribe & Generate MoM" | Transcription via Whisper, MoM generated with meeting context auto-filled, linked to meeting, audio summary generated |
| 14 | Search MoMs by attendee name | Returns matching MoM entries |

---

## 10. Assumptions & Constraints

1. The application assumes a single-user environment (one calendar owner).
2. Google Calendar integration requires a one-time browser-based OAuth consent flow.
3. Audio files larger than 25 MB must be split externally before upload (Whisper API limit).
4. The Mock Calendar mode stores events in memory only (lost on restart); meeting records persist in JSON.
5. Email delivery requires a Gmail account with an app-specific password or a compatible SMTP server.
6. Time zone is hardcoded to Asia/Kolkata (IST) for calendar operations.
7. The NLU model must be capable of function calling (gpt-4o-mini or higher).

---

*Document generated for Smart Office Assistant v1.0*
