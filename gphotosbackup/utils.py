"""Some utils."""
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class DownloadStatus(str, Enum):
    """Download statuses."""
    READY = 'ready'
    NOT_READY = 'not ready'
    ALREADY_DOWNLOADED = 'already downloaded'


class BackupStage(Enum):
    """Backup stages."""
    MEDIA_ITEM = 'mediaitem'
    ALBUM = 'album'
    ALBUM_ITEM = 'albumitem'
    END = 'end'


@dataclass
class DownloadInfo:
    """Information about file to download."""
    id: int
    mediaitem_uid: str
    creation_time: str
    item_type: str
    base_url: str
    filename: str
    original_filename: str
    download_status: DownloadStatus

@contextmanager
def disable_exception_traceback():
    """All traceback information is suppressed."""
    default_value = getattr(sys, "tracebacklimit", 1000)
    sys.tracebacklimit = 0
    yield
    sys.tracebacklimit = default_value

def credentials_to_dict(credentials):
  return {'token': credentials.token,
          'refresh_token': credentials.refresh_token,
          'token_uri': credentials.token_uri,
          'client_id': credentials.client_id,
          'client_secret': credentials.client_secret,
          'scopes': credentials.scopes}

def convert_iso_to_timestamp(iso_time: str) -> Optional[int]:
    """Convert creation time to unix timestamp."""
    if not iso_time:
        return None
    return datetime.fromisoformat(iso_time[:19]).timestamp()
