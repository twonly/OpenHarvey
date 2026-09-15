"""Browser login lifetime shared by all login methods."""
import os


def session_seconds():
    return max(3600, int(os.environ.get('CW_SESSION_TTL_SECONDS', 30 * 86400)))
