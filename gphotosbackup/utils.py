"""Some utils."""
import sys
from contextlib import contextmanager


SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']
API_SERVICE_NAME = 'photoslibrary'
API_VERSION = 'v1'


@contextmanager
def disable_exception_traceback():
    """All traceback information is suppressed."""
    default_value = getattr(sys, "tracebacklimit", 1000)
    sys.tracebacklimit = 0
    yield
    sys.tracebacklimit = default_value
