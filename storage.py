"""
Smart Office Assistant - Data Storage & Persistence
Handles meeting records, MoM storage, and search functionality.
"""
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from config import MEETINGS_FILE, MOMS_DIR, sanitize_user_for_path


class MeetingStore:
    """Manages meeting records with thread tracking. Supports per-user data; admin sees all."""

    def __init__(self, filepath: Optional[Path] = None, user_email: Optional[str] = None, is_admin: bool = False):
        self.filepath = filepath or MEETINGS_FILE
        self.user_email = user_email or ""
        self.is_admin = is_admin
        self.data = self._load()

    def _load(self) -> dict:
        if self.filepath.exists():
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"meetings": [], "threads": {}}

    def save(self):
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False, default=str)

    def _filter_by_user(self, meetings_list: list[dict]) -> list[dict]:
        """Return meetings for current user, or all if admin."""
        if self.is_admin or not self.user_email:
            return meetings_list
        return [m for m in meetings_list if m.get("user_email") == self.user_email]

    @property
    def meetings(self) -> list[dict]:
        return self._filter_by_user(self.data.get("meetings", []))

    def add_meeting(self, meeting_info: dict, parent_meeting_id: Optional[str] = None) -> dict:
        """
        Store a meeting record.
        meeting_info should contain: title, date, time, duration, participants, etc.
        """
        meeting_id = f"mtg_{uuid.uuid4().hex[:10]}"

        # Determine thread
        if parent_meeting_id:
            thread_id = self._get_thread_for_meeting(parent_meeting_id)
            if not thread_id:
                thread_id = f"thread_{uuid.uuid4().hex[:8]}"
        else:
            thread_id = f"thread_{uuid.uuid4().hex[:8]}"

        record = {
            "id": meeting_id,
            "thread_id": thread_id,
            "parent_meeting_id": parent_meeting_id,
            "user_email": self.user_email,
            "title": meeting_info.get("title", "Untitled Meeting"),
            "date": meeting_info.get("date", ""),
            "time": meeting_info.get("time", ""),
            "duration_minutes": meeting_info.get("duration_minutes", 45),
            "participants": meeting_info.get("participants", []),
            "participant_emails": meeting_info.get("participant_emails", []),
            "description": meeting_info.get("description", ""),
            "calendar_event_id": meeting_info.get("calendar_event_id", ""),
            "calendar_event_link": meeting_info.get("calendar_event_link", ""),
            "mom_id": None,
            "status": "scheduled",
            "created_at": datetime.now().isoformat(),
        }

        self.data["meetings"].append(record)

        # Update thread mapping
        if thread_id not in self.data["threads"]:
            self.data["threads"][thread_id] = []
        self.data["threads"][thread_id].append(meeting_id)

        self.save()
        return record

    def _get_thread_for_meeting(self, meeting_id: str) -> Optional[str]:
        """Find the thread ID for a given meeting."""
        for thread_id, meeting_ids in self.data.get("threads", {}).items():
            if meeting_id in meeting_ids:
                return thread_id
        return None

    def get_meeting(self, meeting_id: str) -> Optional[dict]:
        for m in self.meetings:
            if m["id"] == meeting_id:
                return m
        return None

    def get_thread_meetings(self, thread_id: str) -> list[dict]:
        """Get all meetings in a thread, ordered by date."""
        meeting_ids = self.data.get("threads", {}).get(thread_id, [])
        meetings = [m for m in self.meetings if m["id"] in meeting_ids]
        return sorted(meetings, key=lambda x: x.get("created_at", ""))

    def _parse_meeting_datetime(self, date_str: str, time_str: str, duration_minutes: int = 0) -> Optional[tuple]:
        """Parse meeting date/time to (start_dt, end_dt). Returns None if parse fails."""
        if not date_str or not time_str:
            return None
        time_str = time_str.strip()
        t = None
        for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
            try:
                t = datetime.strptime(time_str, fmt).time()
                break
            except ValueError:
                continue
        if t is None:
            return None
        try:
            d = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
        start = datetime.combine(d, t)
        end = start + timedelta(minutes=duration_minutes or 45)
        return (start, end)

    def get_conflicting_meetings(
        self, date_str: str, time_str: str, duration_minutes: int, exclude_meeting_id: Optional[str] = None
    ) -> list[dict]:
        """Return meetings that overlap with the given slot (same user's scheduled meetings only)."""
        slot = self._parse_meeting_datetime(date_str, time_str, duration_minutes)
        if not slot:
            return []
        start_new, end_new = slot
        conflicts = []
        for m in self.meetings:
            if m.get("status") == "cancelled":
                continue
            if exclude_meeting_id and m.get("id") == exclude_meeting_id:
                continue
            existing = self._parse_meeting_datetime(
                m.get("date", ""), m.get("time", ""), m.get("duration_minutes", 45)
            )
            if not existing:
                continue
            start_ex, end_ex = existing
            if start_new < end_ex and end_new > start_ex:
                conflicts.append(m)
        return conflicts

    def get_recent_meetings(self, limit: int = 10) -> list[dict]:
        """Get most recent meetings."""
        sorted_meetings = sorted(
            self.meetings,
            key=lambda x: x.get("created_at", ""),
            reverse=True
        )
        return sorted_meetings[:limit]

    def search_meetings(self, query: str) -> list[dict]:
        """Search meetings by title, participants, or description."""
        q = query.lower()
        results = []
        for m in self.meetings:
            if (q in m.get("title", "").lower() or
                q in m.get("description", "").lower() or
                any(q in p.lower() for p in m.get("participants", []))):
                results.append(m)
        return results

    def _can_modify_meeting(self, meeting: dict) -> bool:
        """Check if current user can modify this meeting. Admin can modify any; legacy (no user_email) editable by admin."""
        if self.is_admin:
            return True
        return meeting.get("user_email") == self.user_email

    def update_meeting(self, meeting_id: str, **kwargs) -> Optional[dict]:
        """Update a meeting record (only own meetings unless admin)."""
        for m in self.data.get("meetings", []):
            if m.get("id") == meeting_id:
                if not self._can_modify_meeting(m):
                    return None
                m.update(kwargs)
                self.save()
                return m
        return None

    def cancel_meeting(self, meeting_id: str) -> Optional[dict]:
        """Mark a meeting as cancelled."""
        return self.update_meeting(meeting_id, status="cancelled")

    def delete_meeting(self, meeting_id: str) -> bool:
        """Permanently delete a meeting (only own unless admin)."""
        meeting = self.get_meeting(meeting_id)
        if not meeting or not self._can_modify_meeting(meeting):
            return False
        original_len = len(self.data["meetings"])
        self.data["meetings"] = [
            m for m in self.data["meetings"] if m["id"] != meeting_id
        ]
        if len(self.data["meetings"]) < original_len:
            # Remove from thread mapping
            for thread_id, mids in list(self.data.get("threads", {}).items()):
                if meeting_id in mids:
                    mids.remove(meeting_id)
                    if not mids:
                        del self.data["threads"][thread_id]
                    break
            self.save()
            return True
        return False

    def find_related_meetings(self, participants: list[str], title_keywords: list[str] = None) -> list[dict]:
        """Find meetings that could be predecessors for a follow-up."""
        results = []
        for m in self.meetings:
            participant_overlap = any(
                p.lower() in [mp.lower() for mp in m.get("participants", [])]
                for p in participants
            )
            title_match = False
            if title_keywords:
                title_match = any(
                    kw.lower() in m.get("title", "").lower()
                    for kw in title_keywords
                )
            if participant_overlap or title_match:
                results.append(m)
        return sorted(results, key=lambda x: x.get("created_at", ""), reverse=True)


class MoMStore:
    """Manages Minutes of Meeting storage and retrieval. Per-user directory; admin sees all."""

    def __init__(self, directory: Optional[Path] = None, user_email: Optional[str] = None, is_admin: bool = False):
        self.user_email = user_email or ""
        self.is_admin = is_admin
        if directory is not None:
            self.directory = directory
        else:
            self.directory = MOMS_DIR / sanitize_user_for_path(self.user_email) if self.user_email else MOMS_DIR
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_file = self.directory / "index.json"
        self.index = self._load_index()

    def _load_index(self) -> dict:
        if self.index_file.exists():
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"moms": []}

    def _save_index(self):
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2, ensure_ascii=False, default=str)

    def store_mom(self, mom_data: dict, meeting_id: Optional[str] = None) -> str:
        """
        Store a MoM document.
        mom_data should contain: title, date, attendees, content, action_items, etc.
        Returns the MoM ID.
        """
        mom_id = f"mom_{uuid.uuid4().hex[:10]}"

        # Store the full MoM as a separate JSON file
        mom_file = self.directory / f"{mom_id}.json"
        mom_record = {
            "id": mom_id,
            "meeting_id": meeting_id,
            "title": mom_data.get("title", "Untitled Meeting"),
            "date": mom_data.get("date", datetime.now().strftime("%Y-%m-%d")),
            "attendees": mom_data.get("attendees", []),
            "content": mom_data.get("content", ""),
            "action_items": mom_data.get("action_items", []),
            "key_discussion_points": mom_data.get("key_discussion_points", []),
            "decisions": mom_data.get("decisions", []),
            "transcript": mom_data.get("transcript", ""),
            "audio_summary_path": mom_data.get("audio_summary_path", ""),
            "created_at": datetime.now().isoformat(),
        }

        with open(mom_file, "w", encoding="utf-8") as f:
            json.dump(mom_record, f, indent=2, ensure_ascii=False)

        # Update index
        index_entry = {
            "id": mom_id,
            "meeting_id": meeting_id,
            "user_email": self.user_email,
            "title": mom_record["title"],
            "date": mom_record["date"],
            "attendees": mom_record["attendees"],
            "action_item_count": len(mom_record["action_items"]),
            "created_at": mom_record["created_at"],
        }
        self.index["moms"].append(index_entry)
        self._save_index()

        return mom_id

    def get_mom(self, mom_id: str, user_email: Optional[str] = None) -> Optional[dict]:
        """Retrieve a full MoM by ID. For admin, pass user_email to load from that user's dir."""
        if user_email and self.is_admin:
            dir_path = MOMS_DIR / sanitize_user_for_path(user_email)
            mom_file = dir_path / f"{mom_id}.json"
        else:
            mom_file = self.directory / f"{mom_id}.json"
        if mom_file.exists():
            with open(mom_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def get_all_moms(self) -> list[dict]:
        """Get index entries for all MoMs (all users if admin)."""
        if self.is_admin:
            # Aggregate from all user directories under MOMS_DIR
            all_entries = []
            for subdir in MOMS_DIR.iterdir():
                if subdir.is_dir():
                    idx_file = subdir / "index.json"
                    if idx_file.exists():
                        try:
                            with open(idx_file, "r", encoding="utf-8") as f:
                                idx = json.load(f)
                            for entry in idx.get("moms", []):
                                entry = dict(entry)
                                if "user_email" not in entry:
                                    entry["user_email"] = ""  # legacy
                                all_entries.append(entry)
                        except (json.JSONDecodeError, OSError):
                            pass
            return sorted(all_entries, key=lambda x: x.get("created_at", ""), reverse=True)
        return sorted(
            self.index.get("moms", []),
            key=lambda x: x.get("created_at", ""),
            reverse=True
        )

    def search_moms(self, query: str) -> list[dict]:
        """Search MoMs by title, attendees, summary, discussion points, decisions, content, and action items."""
        q = (query or "").strip().lower()
        if not q:
            return self.get_all_moms()
        results = []
        for entry in self.index.get("moms", []):
            if (q in entry.get("title", "").lower() or
                any(q in (a or "").lower() for a in entry.get("attendees", []))):
                results.append(entry)
                continue

            # Search full MoM body: summary, key_discussion_points, decisions, content, action_items
            mom_user = entry.get("user_email") if self.is_admin else None
            mom = self.get_mom(entry["id"], mom_user)
            if not mom:
                continue
            searchable_parts = [
                mom.get("summary", ""),
                mom.get("content", ""),
            ]
            searchable_parts.extend(mom.get("key_discussion_points", []))
            searchable_parts.extend(mom.get("decisions", []))
            for ai in mom.get("action_items", []):
                searchable_parts.append(ai.get("description", ""))
            searchable_text = " ".join(str(p) for p in searchable_parts).lower()
            if q in searchable_text:
                results.append(entry)
        return results

    def get_mom_formatted(self, mom_id: str, user_email: Optional[str] = None) -> Optional[str]:
        """Get a MoM formatted as markdown. For admin, pass user_email to load from that user's dir."""
        mom = self.get_mom(mom_id, user_email)
        if not mom:
            return None

        lines = []
        lines.append(f"# Minutes of Meeting: {mom['title']}")
        lines.append(f"\n**Date:** {mom['date']}")
        lines.append(f"**Attendees:** {', '.join(mom.get('attendees', []))}")
        lines.append("")

        if mom.get("key_discussion_points"):
            lines.append("## Key Discussion Points")
            for i, point in enumerate(mom["key_discussion_points"], 1):
                lines.append(f"{i}. {point}")
            lines.append("")

        if mom.get("decisions"):
            lines.append("## Decisions Made")
            for i, decision in enumerate(mom["decisions"], 1):
                lines.append(f"{i}. {decision}")
            lines.append("")

        if mom.get("action_items"):
            lines.append("## Action Items")
            lines.append("| # | Action Item | Owner | Deadline | Status |")
            lines.append("|---|-----------|-------|----------|--------|")
            for i, item in enumerate(mom["action_items"], 1):
                lines.append(
                    f"| {i} | {item.get('description', '')} | "
                    f"{item.get('owner', 'TBD')} | "
                    f"{item.get('deadline', 'TBD')} | "
                    f"{item.get('status', 'Pending')} |"
                )
            lines.append("")

        if mom.get("content"):
            lines.append("## Detailed Notes")
            lines.append(mom["content"])

        return "\n".join(lines)
