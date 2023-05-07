"""Exceptions used by application."""

class InvalidResponse(Exception):
    """Raises when Google Photos returns invalid response."""


class UnknownBackupStage(Exception):
    """Raises when unknown backup stage detected."""

class AlbumNotFound(Exception):
    """Raises when album not found in DB."""