"""Project native titles without leaking runtime placeholders."""
import re
import json


async def prepare_title_model(store, user, thread, runtime, model):
    """Pin the native title agent to the selected model before the idle send.

    A global small_model may belong to a different, unfunded provider. Project
    config also overrides that setting in already-running or resumed runtimes.
    """
    path = store.user_root(user['id']) / 'threads' / thread['id'] / 'opencode.json'
    config = json.loads(path.read_text()) if path.exists() else {}
    title = config.setdefault('agent', {}).setdefault('title', {})
    if title.get('model') == model:
        return
    title['model'] = model
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(config, ensure_ascii=False))
    temp.replace(path)
    # E2B uploads the project config before disposing this directory's instance.
    await runtime.call('POST', '/instance/dispose', tid=thread['id'])


def placeholder(title):
    return not title or title in {'新对话', 'New session', 'New session...'} or bool(re.match(r'^New session\s*-\s*\d{4}-', title))


def resolve_title(thread, native=None):
    if thread.get('custom_title'):return thread['custom_title']
    if native and not placeholder(native):return native
    if not placeholder(thread.get('title')):return thread['title']
    return '新对话'
