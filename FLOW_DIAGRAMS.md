# Smart Office Assistant — Mermaid Flow Diagrams

Copy any diagram below into a Mermaid-compatible renderer
(e.g. [mermaid.live](https://mermaid.live), GitHub markdown, VS Code Mermaid plugin).

---

## 1. Application High-Level Architecture

```mermaid
graph TB
    User([User]) -->|text / voice| ChatPage[Chat Page]
    User -->|browse| AddrPage[Address Book Page]
    User -->|browse| MtgPage[Meetings Page]
    User -->|browse| MoMPage[MoM Archive Page]
    User -->|browse| SettingsPage[Settings Page]

    subgraph "Streamlit App (app.py)"
        LoginScreen[Login Screen] -->|verify_user| Auth[auth.py]
        LoginScreen -->|success| Sidebar[Sidebar Navigation]
        Sidebar --> ChatPage
        Sidebar --> AddrPage
        Sidebar --> MtgPage
        Sidebar --> MoMPage
        Sidebar --> SettingsPage
    end

    ChatPage -->|process_message| MM[Meeting Manager]
    MtgPage -->|upload recording| TransSvc[Transcription Service]
    MtgPage -->|cancel / delete| MtgStore[Meeting Store]
    MoMPage -->|search / view| MoMStore[MoM Store]
    AddrPage -->|CRUD| AddrBook[Address Book]

    MM -->|parse_command| NLU[NLU Engine]
    MM -->|create_event| CalSvc[Calendar Service]
    MM -->|add_meeting| MtgStore
    MM -->|resolve_participant| AddrBook
    MM -->|send_email| Comms[Communication]

    TransSvc -->|transcript| MoMGen[MoM Generator]
    MoMGen -->|store_mom| MoMStore
    MoMGen -->|action items| Comms

    NLU -->|OpenAI GPT| OpenAI[(OpenAI API)]
    TransSvc -->|Whisper| OpenAI
    MoMGen -->|GPT function calling| OpenAI
    Comms -->|TTS| OpenAI
    Comms -->|SMTP| Email[(Email Server)]
    CalSvc -->|Calendar API| GCal[(Google Calendar)]

    MtgStore -->|JSON| Disk[(Local JSON Files)]
    MoMStore -->|JSON| Disk
    AddrBook -->|JSON| Disk
```

---

## 2. Authentication Flow

```mermaid
flowchart TD
    Start([App Start]) --> CheckSession{Session has\nuser_email?}
    CheckSession -->|Yes| MainApp[Render Main App]
    CheckSession -->|No| LoginScreen[Show Login Screen]

    LoginScreen --> UserInput[User enters\nemail + password]
    UserInput --> VerifyUser[auth.verify_user\nemail, password]
    VerifyUser --> LoadJSON[Load login.json]
    LoadJSON --> MatchUser{Match found?}
    MatchUser -->|Yes| CheckRole{role == Admin?}
    MatchUser -->|No| ShowError[Show error message]
    ShowError --> LoginScreen

    CheckRole -->|Yes| SetAdmin[Set is_admin = True]
    CheckRole -->|No| SetRegular[Set is_admin = False]
    SetAdmin --> SetSession[Set session state:\nuser_email, is_admin]
    SetRegular --> SetSession
    SetSession --> InitServices[Initialize per-user:\nAddressBook, MeetingStore,\nMoMStore, MeetingManager]
    InitServices --> MainApp
```

---

## 3. Meeting Scheduling — Conversation State Machine

```mermaid
stateDiagram-v2
    [*] --> IDLE

    IDLE --> IDLE : list_meetings / search_mom /\nupload_recording / general_chat
    IDLE --> COLLECTING_INFO : schedule_meeting\n(missing fields)
    IDLE --> AWAITING_DISAMBIGUATION : schedule_meeting\n(ambiguous participant)
    IDLE --> AWAITING_CONFIRMATION : schedule_meeting\n(all fields present)
    IDLE --> AWAITING_SLOT_CHOICE : schedule_meeting\n(use_first_available)

    COLLECTING_INFO --> COLLECTING_INFO : still missing fields
    COLLECTING_INFO --> AWAITING_CONFIRMATION : all fields gathered
    COLLECTING_INFO --> AWAITING_SLOT_CHOICE : first available requested
    COLLECTING_INFO --> IDLE : non-scheduling intent detected

    AWAITING_DISAMBIGUATION --> COLLECTING_INFO : participant resolved,\nmissing fields remain
    AWAITING_DISAMBIGUATION --> AWAITING_CONFIRMATION : participant resolved,\nall complete
    AWAITING_DISAMBIGUATION --> AWAITING_DISAMBIGUATION : still ambiguous

    AWAITING_SLOT_CHOICE --> AWAITING_CONFIRMATION : slot chosen / auto-selected
    AWAITING_SLOT_CHOICE --> COLLECTING_INFO : no slots available,\nask for different date

    AWAITING_CONFIRMATION --> IDLE : confirmed → execute_scheduling\n→ create event → store meeting
    AWAITING_CONFIRMATION --> IDLE : cancelled
    AWAITING_CONFIRMATION --> COLLECTING_INFO : modification requested
```

---

## 4. Meeting Scheduling — Detailed Execution Flow

```mermaid
flowchart TD
    UserMsg([User Message]) --> ProcessMsg[MeetingManager.\nprocess_message]

    ProcessMsg --> CheckState{Current State?}

    CheckState -->|IDLE| ParseCmd[nlu_engine.\nparse_command]
    CheckState -->|COLLECTING_INFO| CheckIntent{New intent\ndetected?}
    CheckState -->|AWAITING_CONFIRMATION| Classify[nlu_engine.\nclassify_confirmation]
    CheckState -->|AWAITING_DISAMBIGUATION| ReResolve[Re-resolve\nparticipants]
    CheckState -->|AWAITING_SLOT_CHOICE| ParseSlot[Parse slot\nchoice]

    CheckIntent -->|Yes, different| ResetIdle[Reset → IDLE]
    ResetIdle --> ParseCmd
    CheckIntent -->|No, continuation| UpdateFields[Update pending\nmeeting fields]

    ParseCmd --> GetIntent{Intent?}
    GetIntent -->|schedule_meeting| StartSched[_start_scheduling]
    GetIntent -->|list_meetings| ListMtgs[_list_meetings]
    GetIntent -->|general_chat| ChatReply[Return response]
    GetIntent -->|other intents| HandleOther[Route to handler]

    StartSched --> ResolvePart[_resolve_all_participants\nvia AddressBook]
    ResolvePart --> AmbigCheck{Ambiguous?}
    AmbigCheck -->|Yes| AskDisambig[Ask user to\nclarify → AWAITING_DISAMBIGUATION]
    AmbigCheck -->|No| CheckMissing[_compute_missing_fields]

    UpdateFields --> CheckMissing

    CheckMissing --> MissingCheck{Fields missing?}
    MissingCheck -->|Yes| AskFollowup[generate_followup_question\n→ COLLECTING_INFO]
    MissingCheck -->|No| CheckFirstAvail{use_first_available?}

    CheckFirstAvail -->|Yes| FindSlot[calendar.\nfind_first_available_slot]
    FindSlot --> SlotFound{Slot found?}
    SlotFound -->|Yes| SetTime[Set time from slot]
    SlotFound -->|No| AskDate[Ask for different\ndate → COLLECTING_INFO]
    CheckFirstAvail -->|No| Confirm

    SetTime --> Confirm[_present_confirmation\n→ AWAITING_CONFIRMATION]

    Classify --> ConfResult{Result?}
    ConfResult -->|confirmed| Execute[_execute_scheduling]
    ConfResult -->|cancelled| Cancel[Reset → IDLE]
    ConfResult -->|modification| BackCollect[→ COLLECTING_INFO]

    Execute --> CreateEvent[calendar_service.\ncreate_event]
    CreateEvent --> StoreMeeting[meeting_store.\nadd_meeting]
    StoreMeeting --> SendEmail[communication.\nsend_meeting_invite]
    SendEmail --> SuccessMsg([Success message\n+ calendar link])
```

---

## 5. NLU Engine — Command Parsing Flow

```mermaid
flowchart TD
    Input([User message +\nconversation history]) --> BuildPrompt[Build system prompt\nwith today's date]
    BuildPrompt --> AddHistory[Append last 10\nconversation messages]
    AddHistory --> AddMsg[Add current\nuser message]
    AddMsg --> CallGPT[OpenAI Chat Completions\nmodel: gpt-4o-mini\ntemp: 0.1\ntools: process_command]
    CallGPT --> ParseJSON[Parse function call\nJSON arguments]
    ParseJSON --> Result([Structured result:\nintent, meeting_details,\nmissing_fields,\nresponse_message])

    Result --> IntentTypes{Intent Type}
    IntentTypes --> |schedule_meeting| SchedData[participants, date,\ntime, duration, title]
    IntentTypes --> |reschedule_meeting| ReschedData[meeting reference,\nnew date/time]
    IntentTypes --> |cancel_meeting| CancelData[meeting reference]
    IntentTypes --> |add/remove_attendees| AttData[meeting reference,\nparticipants]
    IntentTypes --> |list_meetings| ListData[no extra data]
    IntentTypes --> |search_mom| SearchData[search_query]
    IntentTypes --> |general_chat| ChatData[response_message]
```

---

## 6. Recording Upload & MoM Generation Flow

```mermaid
flowchart TD
    MeetingPage([Meetings Page:\nclick Upload Recording]) --> ShowUploader[Show file uploader\ninside meeting expander]
    ShowUploader --> UploadFile[User uploads\naudio/video file]
    UploadFile --> SelectLang[User selects\nlanguage]

    SelectLang --> ChooseAction{Action?}
    ChooseAction -->|Transcribe Only| TransOnly[Transcribe only]
    ChooseAction -->|Transcribe & Generate MoM| FullFlow[Full pipeline]

    TransOnly --> Validate[Validate format\n+ file size]
    FullFlow --> Validate

    Validate --> ValidCheck{Valid?}
    ValidCheck -->|No| ShowError[Show error message]
    ValidCheck -->|Yes| WriteTemp[Write to temp file]

    WriteTemp --> CallWhisper[OpenAI Whisper API\nmodel: whisper-1]
    CallWhisper --> Transcript([Transcript text +\nduration + language])

    Transcript --> TransOnlyCheck{Transcribe only?}
    TransOnlyCheck -->|Yes| DisplayTranscript[Display transcript\nin text area]
    TransOnlyCheck -->|No| GenMoM[mom_generator.\ngenerate_mom_from_transcript]

    GenMoM --> BuildContext[Build context:\ntranscript + meeting title\n+ attendees + date]
    BuildContext --> CallGPT[OpenAI GPT\nfunction calling:\ngenerate_mom tool]
    CallGPT --> MoMData([Structured MoM:\ntitle, summary,\ndiscussion points,\ndecisions, action items])

    MoMData --> StoreMoM[mom_store.\nstore_mom\nlinked to meeting_id]
    StoreMoM --> UpdateMeeting[meeting_store.\nupdate_meeting\nset mom_id + status=completed]
    UpdateMeeting --> DisplayMoM[Display formatted\nMoM in UI]
    DisplayMoM --> GenAudio[communication.\ngenerate_action_items_audio]
    GenAudio --> PlayAudio([Play audio\nsummary in browser])
```

---

## 7. Communication Flow — TTS & Email

```mermaid
flowchart TD
    subgraph "Text-to-Speech"
        ActionItems([Action items list]) --> BuildText[Build narration text:\nItem 1: description.\nAssigned to owner.]
        BuildText --> CallTTS[OpenAI TTS API\nmodel: tts-1\nvoice: alloy]
        CallTTS --> StreamFile[Stream to\naudio_output/*.mp3]
        StreamFile --> AudioFile([MP3 file path])
    end

    subgraph "Email MoM"
        MoMData([MoM data]) --> BuildHTML[_build_mom_email_html:\ngradient header,\ndiscussion points,\naction items table]
        MoMData --> BuildText2[_build_mom_email_text:\nplain text fallback]
        AudioFile -.->|optional attachment| Attach[Add audio attachment]

        BuildHTML --> CreateMIME[Create MIMEMultipart\n+ HTML + text parts]
        BuildText2 --> CreateMIME
        Attach --> CreateMIME

        CreateMIME --> LookupEmails[Look up attendee\nemails from AddressBook]
        LookupEmails --> SMTP[SMTP: connect → starttls\n→ login → sendmail]
        SMTP --> Sent([Email sent to attendees])
    end

    subgraph "Meeting Invite Email"
        MeetingDetails([Meeting details]) --> InviteHTML[Build invite HTML\nwith calendar + Meet links]
        InviteHTML --> SendInvite[send_email to\neach participant]
        SendInvite --> InviteSent([Invites sent])
    end
```

---

## 8. Data Storage Architecture

```mermaid
flowchart TD
    subgraph "Per-User Storage"
        AddrBook[Address Book\naddress_book_user_email.json] --> |contacts, departments| AddrOps[CRUD: add, update,\ndelete, search, resolve]
        ChatHist[Chat History\nchat_user_email.json] --> |messages array| ChatOps[Save/load\nper session]
        MoMFiles[MoM Files\nmoms/user_email/\nmom_id.json + index.json] --> |full MoM + index| MoMOps[Store, get,\nsearch, format]
    end

    subgraph "Shared Storage"
        Meetings[Meetings\nmeetings.json] --> |meetings array + threads map| MtgOps[Add, update, cancel,\ndelete, search]
        LoginData[Login Data\nlogin.json] --> |users array| AuthOps[Verify, add user]
    end

    subgraph "Meeting Record"
        MtgRecord[/"id, thread_id, parent_meeting_id,\ntitle, date, time, duration,\nparticipants, participant_emails,\ncalendar_event_id, mom_id,\nstatus, created_by, created_at"/]
    end

    subgraph "MoM Record"
        MoMRecord[/"id, meeting_id, title, date,\nattendees, summary,\nkey_discussion_points, decisions,\naction_items, transcript,\naudio_summary_path, created_at"/]
    end

    subgraph "Action Item"
        ActionItem[/"description, owner,\ndeadline, priority, status"/]
    end

    MtgOps --> MtgRecord
    MoMOps --> MoMRecord
    MoMRecord --> ActionItem
```

---

## 9. Calendar Service Flow

```mermaid
flowchart TD
    subgraph "Authentication"
        Start([Initialize]) --> CheckLib{Google API\nlibraries installed?}
        CheckLib -->|No| MockMode[Use MockCalendarService]
        CheckLib -->|Yes| CheckCreds{credentials.json\nexists?}
        CheckCreds -->|No| MockMode
        CheckCreds -->|Yes| CheckToken{token.json\nexists & valid?}
        CheckToken -->|Yes| BuildService[Build Calendar\nservice v3]
        CheckToken -->|No, expired| Refresh[Refresh token]
        CheckToken -->|No, missing| OAuthFlow[OAuth2 browser\nconsent flow]
        Refresh --> SaveToken[Save token.json]
        OAuthFlow --> SaveToken
        SaveToken --> BuildService
        BuildService --> Ready([Calendar Ready])
    end

    subgraph "Create Event"
        EventInput([title, datetime,\nduration, attendees]) --> BuildBody[Build event body:\nstart/end, timezone IST,\nreminders, attendees,\nconferenceData for Meet]
        BuildBody --> InsertAPI[events.insert API\nsendUpdates: all]
        InsertAPI --> EventResult([event_id, html_link,\nmeet_link])
    end

    subgraph "Check Availability"
        DateInput([target date,\nduration]) --> FreeBusy[freebusy.query API\n9 AM - 6 PM IST]
        FreeBusy --> BusyPeriods[Parse busy periods]
        BusyPeriods --> GenSlots[Generate 30-min\nincrement slots]
        GenSlots --> FilterSlots[Remove slots\noverlapping busy]
        FilterSlots --> AvailSlots([Available slots\nlist])
    end
```

---

## 10. End-to-End: Schedule a Meeting

```mermaid
sequenceDiagram
    actor User
    participant App as Streamlit App
    participant MM as Meeting Manager
    participant NLU as NLU Engine
    participant AB as Address Book
    participant Cal as Calendar Service
    participant Store as Meeting Store
    participant Email as Communication

    User->>App: "Schedule a meeting with Rohit from<br/>Digital Marketing next Monday at 2pm"
    App->>MM: process_message(text)
    MM->>NLU: parse_command(text, history)
    NLU->>NLU: OpenAI GPT → extract intent + entities
    NLU-->>MM: {intent: schedule_meeting,<br/>participants: [{name: Rohit, dept: Digital Marketing}],<br/>date: 2026-02-16, time: 14:00,<br/>missing_fields: [duration]}

    MM->>AB: resolve_participant("Rohit", "Digital Marketing")
    AB-->>MM: [Rohit Sharma contact]

    MM-->>App: "How long should the meeting be?"
    App-->>User: Display follow-up question

    User->>App: "45 minutes"
    App->>MM: process_message("45 minutes")
    MM->>MM: Parse duration → 45 min
    MM->>MM: All fields present → generate confirmation

    MM-->>App: "Title: Meeting with Rohit Sharma<br/>Date: Monday Feb 16<br/>Time: 2:00 PM (45 min)<br/>Confirm?"
    App-->>User: Display confirmation

    User->>App: "Yes"
    App->>MM: process_message("Yes")
    MM->>NLU: classify_confirmation → "confirmed"
    MM->>Cal: create_event(title, datetime, 45, attendees)
    Cal-->>MM: {success, event_id, html_link, meet_link}
    MM->>Store: add_meeting(meeting_info)
    Store-->>MM: meeting_record
    MM->>Email: send_meeting_invite_to_participants(...)
    Email-->>MM: {success}

    MM-->>App: "Meeting scheduled! ✓<br/>Calendar link + Meet link"
    App-->>User: Display success message
```

---

*Use these diagrams at [mermaid.live](https://mermaid.live) or any Mermaid-compatible renderer.*
