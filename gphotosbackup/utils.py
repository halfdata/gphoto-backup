"""Some utils."""
import os
import requests
import shutil
import sys

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Any, Tuple


THUMBNAILS_FOLDER = 'thumbnails'
ITEMS_PER_PAGE = 100


class DownloadStatus(str, Enum):
    """Download statuses."""
    ITEM_AND_THUMBNAIL = 'both'
    THUMBNAIL_ONLY = 'thumbnail only'
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
    thumbnail: str
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

def download_file(url: str, filename: str,
                  filetime: Optional[str] = None) -> Tuple[int, Any]:
    """Download file."""
    try:
        with requests.get(url, timeout=(5, None), stream=True) as r:
            r.raise_for_status()
            with open(filename, 'wb') as f:
                shutil.copyfileobj(r.raw, f)
            os.utime(filename, times=(filetime, filetime))
    except requests.exceptions.HTTPError as e:
        return e.response.status_code, e
    except Exception:
        if os.path.exists(filename):
            print(f'{filename} - failed to download')
            os.remove(filename)
        with disable_exception_traceback():
            raise
    return 200, None
