"""One source catalog for runtime input and historical source navigation."""
import json


def enabled(store, user):
    row = store.one('SELECT preferences FROM users WHERE id=?', (user['id'],))
    return bool(row and json.loads(row['preferences']).get('materials_enabled') is True)


def documents(store, user, thread, history=False):
    workspace = store.one('SELECT * FROM workspaces WHERE id=? AND user_id=?',
                          (thread['workspace_id'], user['id']))
    if not workspace:
        return []
    shared = workspace['backend'] == 'e2b' or enabled(store, user)
    rows = store.all('SELECT * FROM documents WHERE user_id=? AND workspace_id=? ORDER BY rowid',
                     (user['id'], workspace['id']))
    result = []
    for row in rows:
        primary = row['id'] == workspace['document_id']
        available = not row['removed_at'] and (shared or primary or row['thread_id'] == thread['id'])
        # Sources once shared by the owner remain readable in old answers after
        # Labs is disabled. They never re-enter the next task's material scope.
        if available or (history and (row['shared_at'] or shared or row['thread_id'] == thread['id'])):
            result.append({**row, 'primary': primary, 'historical_only': not available})
    return result
