"""
Smart Office Assistant - Data Storage & Persistence
Handles meeting records, MoM storage, and search functionality.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from config import MEETINGS_FILE, MOMS_DIR


class MeetingStore:
    """Manages meeting records with thread tracking."""

    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = filepath or MEETINGS_FILE
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

    @property
    def meetings(self) -> list[dict]:
        return self.data.get("meetings", [])

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

    def update_meeting(self, meeting_id: str, **kwargs) -> Optional[dict]:
        """Update a meeting record."""
        for m in self.data["meetings"]:
            if m["id"] == meeting_id:
                m.update(kwargs)
                self.save()
                return m
        return None

    def cancel_meeting(self, meeting_id: str) -> Optional[dict]:
        """Mark a meeting as cancelled."""
        return self.update_meeting(meeting_id, status="cancelled")

    def delete_meeting(self, meeting_id: str) -> bool:
        """Permanently delete a meeting and remove it from its thread."""
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
    """Manages Minutes of Meeting storage and retrieval."""

    def __init__(self, directory: Optional[Path] = None):
        self.directory = directory or MOMS_DIR
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
            "title": mom_record["title"],
            "date": mom_record["date"],
            "attendees": mom_record["attendees"],
            "action_item_count": len(mom_record["action_items"]),
            "created_at": mom_record["created_at"],
        }
        self.index["moms"].append(index_entry)
        self._save_index()

        return mom_id

    def get_mom(self, mom_id: str) -> Optional[dict]:
        """Retrieve a full MoM by ID."""
        mom_file = self.directory / f"{mom_id}.json"
        if mom_file.exists():
            with open(mom_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def get_all_moms(self) -> list[dict]:
        """Get index entries for all MoMs."""
        return sorted(
            self.index.get("moms", []),
            key=lambda x: x.get("created_at", ""),
            reverse=True
        )

    def search_moms(self, query: str) -> list[dict]:
        """Search MoMs by title, attendees, or content."""
        q = query.lower()
        results = []
        for entry in self.index.get("moms", []):
            if (q in entry.get("title", "").lower() or
                any(q in a.lower() for a in entry.get("attendees", []))):
                results.append(entry)
                continue

            # Search full content
            mom = self.get_mom(entry["id"])
            if mom and (q in mom.get("content", "").lower() or
                        any(q in ai.get("description", "").lower()
                            for ai in mom.get("action_items", []))):
                results.append(entry)

        return results

    def get_mom_formatted(self, mom_id: str) -> Optional[str]:
        """Get a MoM formatted as markdown."""
        mom = self.get_mom(mom_id)
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
