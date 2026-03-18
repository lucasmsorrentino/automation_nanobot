"""Domain models for the UFPR Automation system.

Contains data classes representing the core entities the system works with.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EmailData:
    """Represents a single email extracted from the OWA inbox.

    Attributes:
        sender: Name or email address of the sender.
        subject: Email subject line.
        preview: First lines of the email body (preview text).
        is_unread: Whether the email has been read.
        timestamp: When the email was received (if available).
    """

    sender: str = ""
    subject: str = ""
    preview: str = ""
    is_unread: bool = False
    timestamp: str = ""

    def __str__(self) -> str:
        status = "📩" if self.is_unread else "📧"
        return f"{status} [{self.sender}] {self.subject}"

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "sender": self.sender,
            "subject": self.subject,
            "preview": self.preview,
            "is_unread": self.is_unread,
            "timestamp": self.timestamp,
        }
