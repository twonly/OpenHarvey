"""Explicit, loopback-only local preview login; never enabled by default."""
import os
import secrets
import time

from .session_policy import session_seconds
from .store import digest


def bootstrap_session(request, store, cookie):
    username = os.environ.get('CW_LOCAL_DEV_USER', '')
    if not username or request.method != 'GET' or request.url.path not in {'/api/me', '/login'}:
        return
    if request.url.hostname not in {'localhost', '127.0.0.1', '::1'} or not request.client or request.client.host not in {'127.0.0.1', '::1'}:
        return
    if request.headers.get('sec-fetch-site') == 'cross-site' or request.headers.get('forwarded') or request.headers.get('x-forwarded-for'):
        return
    request.state.local_preview = True
    if store.authenticate(request.cookies.get(cookie, '')):
        return
    u = store.one('SELECT * FROM users WHERE username=?', (username,))
    if not u:
        store.add_user(username, secrets.token_urlsafe(48))
        u = store.one('SELECT * FROM users WHERE username=?', (username,))
    if not u['active'] or (u.get('expires_at') and u['expires_at'] <= time.time()):
        return
    token = secrets.token_urlsafe(32)
    store.execute('INSERT INTO logins VALUES(?,?,?)', (digest(token), u['id'], time.time()+session_seconds()))
    # All existing authentication paths continue to use a real session cookie.
    cookies = {**request.cookies, cookie: token}
    request.scope['headers'] = [(k, v) for k, v in request.scope['headers'] if k.lower() != b'cookie'] + [(b'cookie', '; '.join(f'{k}={v}' for k, v in cookies.items()).encode())]
    request._cookies = cookies
    return token
