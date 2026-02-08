"""
Smart Office Assistant - Address Book Management
Handles contact storage, lookup, and department queries.
"""
import json
import uuid
from pathlib import Path
from typing import Optional
from config import ADDRESS_BOOK_FILE


class AddressBook:
    """Manages the office address book with contacts and departments."""

    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = filepath or ADDRESS_BOOK_FILE
        self.data = self._load()

    # ─── Persistence ─────────────────────────────────────────────────────
    def _load(self) -> dict:
        """Load address book from JSON file."""
        if self.filepath.exists():
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"user": {}, "contacts": []}

    def save(self):
        """Save address book to JSON file."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    # ─── User (Self) ─────────────────────────────────────────────────────
    @property
    def user(self) -> dict:
        return self.data.get("user", {})

    @property
    def contacts(self) -> list[dict]:
        return self.data.get("contacts", [])

    # ─── Lookup Methods ──────────────────────────────────────────────────
    def find_by_name(self, name: str) -> list[dict]:
        """Find contacts whose name contains the search string (case-insensitive)."""
        name_lower = name.strip().lower()
        results = []
        for c in self.contacts:
            if name_lower in c["name"].lower():
                results.append(c)
        return results

    def find_by_exact_name(self, name: str) -> Optional[dict]:
        """Find a contact by exact name match (case-insensitive)."""
        name_lower = name.strip().lower()
        for c in self.contacts:
            if c["name"].lower() == name_lower:
                return c
        return None

    def find_by_first_name(self, first_name: str) -> list[dict]:
        """Find contacts by first name (case-insensitive)."""
        fn_lower = first_name.strip().lower()
        return [c for c in self.contacts if c["name"].lower().split()[0] == fn_lower]

    def find_by_department(self, department: str) -> list[dict]:
        """Find all contacts in a department (case-insensitive)."""
        dept_lower = department.strip().lower()
        return [c for c in self.contacts if c.get("department", "").lower() == dept_lower]

    def find_by_email(self, email: str) -> Optional[dict]:
        """Find a contact by email address."""
        email_lower = email.strip().lower()
        for c in self.contacts:
            if c.get("email", "").lower() == email_lower:
                return c
        return None

    def find_by_id(self, contact_id: str) -> Optional[dict]:
        """Find a contact by ID."""
        for c in self.contacts:
            if c.get("id") == contact_id:
                return c
        return None

    def resolve_participant(self, name: str, department: Optional[str] = None) -> list[dict]:
        """
        Resolve a participant reference to actual contacts.
        Handles: exact name, first name, first name + department disambiguation.
        """
        # Try exact name match first
        exact = self.find_by_exact_name(name)
        if exact:
            return [exact]

        # Try first name
        first_name_matches = self.find_by_first_name(name)

        if department:
            # Filter by department
            dept_lower = department.strip().lower()
            filtered = [c for c in first_name_matches
                        if c.get("department", "").lower() == dept_lower]
            if filtered:
                return filtered

        if len(first_name_matches) == 1:
            return first_name_matches

        # Try partial name match
        partial = self.find_by_name(name)
        if department:
            dept_lower = department.strip().lower()
            filtered = [c for c in partial
                        if c.get("department", "").lower() == dept_lower]
            if filtered:
                return filtered

        return partial if partial else first_name_matches

    # ─── Department Operations ───────────────────────────────────────────
    def get_departments(self) -> list[str]:
        """Get a sorted list of all unique departments."""
        depts = set()
        for c in self.contacts:
            if c.get("department"):
                depts.add(c["department"])
        return sorted(depts)

    def get_department_members(self, department: str) -> list[dict]:
        """Get all members of a department."""
        return self.find_by_department(department)

    # ─── CRUD Operations ─────────────────────────────────────────────────
    def add_contact(self, name: str, email: str, department: str = "",
                    role: str = "", phone: str = "") -> dict:
        """Add a new contact to the address book."""
        contact = {
            "id": f"c{str(uuid.uuid4())[:8]}",
            "name": name,
            "email": email,
            "department": department,
            "role": role,
            "phone": phone,
        }
        self.data["contacts"].append(contact)
        self.save()
        return contact

    def update_contact(self, contact_id: str, **kwargs) -> Optional[dict]:
        """Update an existing contact's fields."""
        for c in self.data["contacts"]:
            if c["id"] == contact_id:
                for key, value in kwargs.items():
                    if key in ("name", "email", "department", "role", "phone"):
                        c[key] = value
                self.save()
                return c
        return None

    def delete_contact(self, contact_id: str) -> bool:
        """Delete a contact by ID."""
        original_len = len(self.data["contacts"])
        self.data["contacts"] = [
            c for c in self.data["contacts"] if c["id"] != contact_id
        ]
        if len(self.data["contacts"]) < original_len:
            self.save()
            return True
        return False

    # ─── Utility ─────────────────────────────────────────────────────────
    def get_emails_for_contacts(self, contacts: list[dict]) -> list[str]:
        """Extract email addresses from a list of contact dicts."""
        return [c["email"] for c in contacts if c.get("email")]

    def format_contact(self, contact: dict) -> str:
        """Format a contact for display."""
        parts = [contact["name"]]
        if contact.get("role"):
            parts.append(f"({contact['role']})")
        if contact.get("department"):
            parts.append(f"- {contact['department']}")
        return " ".join(parts)

    def format_contacts_list(self, contacts: list[dict]) -> str:
        """Format a list of contacts for display."""
        if not contacts:
            return "No contacts found."
        return "\n".join(f"  • {self.format_contact(c)}" for c in contacts)

    def search(self, query: str) -> list[dict]:
        """General search across name, email, department, role."""
        q = query.strip().lower()
        results = []
        for c in self.contacts:
            if (q in c.get("name", "").lower() or
                q in c.get("email", "").lower() or
                q in c.get("department", "").lower() or
                q in c.get("role", "").lower()):
                results.append(c)
        return results
