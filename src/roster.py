"""Roster management for squad members."""

import json
from typing import Literal
from pydantic import BaseModel


class Member(BaseModel):
    """Represents a squad member."""

    name: str
    title: Literal["Chief", "Member"]
    squad: Literal[34, 35, 42, 43, 54]
    groupme_name: str


class Roster:
    """Manages the roster of squad members."""

    def __init__(self, roster_file_path: str):
        """Initialize the roster from a JSON file."""
        self.roster_file_path = roster_file_path
        self.members: list[Member] = []
        self._load_roster()

    def _load_roster(self) -> None:
        """Load roster from JSON file."""
        try:
            with open(self.roster_file_path, "r") as f:
                data = json.load(f)
                self.members = [Member(**member) for member in data["members"]]
        except FileNotFoundError:
            raise FileNotFoundError(f"Roster file not found: {self.roster_file_path}")
        except Exception as e:
            raise Exception(f"Error loading roster: {e}")

    def find_member_by_name(self, name: str) -> Member | None:
        """Find a member by their GroupMe name (case-insensitive)."""
        name_lower = name.lower()
        for member in self.members:
            if member.groupme_name.lower() == name_lower:
                return member
        return None

    def is_authorized(self, name: str) -> bool:
        """Check if a person is in the roster."""
        return self.find_member_by_name(name) is not None

    def get_member_squad(self, name: str) -> int | None:
        """Get the squad number for a member."""
        member = self.find_member_by_name(name)
        return member.squad if member else None

    def get_member_role(self, name: str) -> str | None:
        """Get the role for a member."""
        member = self.find_member_by_name(name)
        return member.title if member else None
