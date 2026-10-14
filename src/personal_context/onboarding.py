"""Create private runtime state; never import the maintainer's configuration."""
import argparse
import json
import os
import secrets
from pathlib import Path
import sys
from .store import Store


def initialize(root=None, *, demo=False, iphone=False):
    root = Path(root or Path.home() / '.local/share/personal-context-bridge/runtime').expanduser()
    if root.is_symlink():
        raise ValueError('runtime directory must not be a symlink')
    root = root.resolve()
    for parent in (root, *root.parents):
        if (parent / '.git').exists() or (parent / 'pyproject.toml').exists():
            raise ValueError('choose a private runtime directory outside the source checkout')
    names = ('archive.key', 'context.sqlite3', 'mcp.json', 'apple.json', 'canvas.json', 'health.sqlite3', 'travel.sqlite3', 'health.token', 'owntracks.password', 'receivers.json')
    if any((root / name).exists() or (root / name).is_symlink() for name in names):
        raise FileExistsError('runtime already initialized; refusing to overwrite')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    key = root / 'archive.key'; db = root / 'context.sqlite3'
    with key.open('xb') as file:
        os.chmod(key, 0o600)
        file.write(os.urandom(32))
    store = Store(db, key_file=key)
    try:
        if demo:
            for kind, source, title, body in (
                ('calendar', 'apple-pim', 'Fictional demo appointment', 'A made-up calendar entry.'),
                ('reminder', 'apple-pim', 'Fictional demo task', 'A made-up reminder.'),
                ('note', 'apple-local', 'Fictional demo note', 'A made-up note for testing search.')):
                store.ingest({'schema': 1, 'source': source, 'kind': kind,
                    'scope': 'demo', 'collected_at': '2026-01-01T00:00:00Z',
                    'complete': True, 'records': [{'id': 'demo-' + kind, 'title': title,
                    'body': body, 'start': '2026-01-02T12:00:00Z', 'payload': {}}]})
    finally:
        store.close()
    config = {'mcpServers': {'personal-context': {'command': sys.executable,
        'args': ['-m', 'personal_context.mcp_server'], 'env': {
            'PERSONAL_CONTEXT_DB': str(db), 'PERSONAL_CONTEXT_KEY_FILE': str(key)}}}}
    if iphone:
        from sqlcipher3 import dbapi2 as cipher
        from iphone_context.health_receiver import SCHEMA as health_schema
        from iphone_context.location_receiver import SCHEMA as travel_schema
        for source, schema in (('health', health_schema), ('travel', travel_schema)):
            path = root / (source + '.sqlite3')
            connection = cipher.connect(str(path))
            try:
                connection.execute("PRAGMA key = \"x'" + key.read_bytes().hex() + "'\"")
                connection.executescript(schema)
            finally:
                connection.close()
            path.chmod(0o600)
            config['mcpServers'][source] = {'command': sys.executable,
                'args': ['-m', 'iphone_context.read_mcp', '--source', source],
                'env': {'IPHONE_ARCHIVE_KEY_FILE': str(key),
                        'IPHONE_' + source.upper() + '_DB': str(path)}}
        for name in ('health.token', 'owntracks.password'):
            with (root / name).open('x') as file:
                os.chmod(root / name, 0o600)
                file.write(secrets.token_urlsafe(32) + '\n')
    templates = {'mcp.json': config,
        'apple.json': {'calendar_ids': [], 'reminder_ids': [], 'mailbox_urls': [],
            'all_calendars': False, 'all_reminders': False, 'all_contacts': False,
            'all_mailboxes': False, 'all_messages': False, 'all_notes': False,
            'remote_host': 'archive-server', 'remote_project': '/srv/personal-context-bridge',
            'remote_data_dir': '/srv/private-context', 'from_date': '2020-01-01', 'to_date': '2030-12-31'},
        'canvas.json': {'base_url': 'https://canvas.example.invalid', 'account': 'school',
            'token_file': str(root / 'canvas.token'), 'download_files': False}}
    if iphone:
        templates['receivers.json'] = {
            'health': {'PULS_TOKEN_FILE': str(root / 'health.token'), 'PULS_KEY_FILE': str(key),
                       'PULS_DB': str(root / 'health.sqlite3')},
            'travel': {'OWNTRACKS_CREDENTIAL_FILE': str(root / 'owntracks.password'),
                       'OWNTRACKS_KEY_FILE': str(key), 'OWNTRACKS_DB': str(root / 'travel.sqlite3')}}
    for name, value in templates.items():
        path = root / name
        with path.open('x') as file:
            os.chmod(path, 0o600)
            json.dump(value, file, indent=2); file.write('\n')
    return {'database': str(db), 'key_file': str(key), 'client_config': str(root / 'mcp.json'), 'demo': demo}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', help='private directory outside the checkout')
    parser.add_argument('--demo', action='store_true', help='seed three fictional records')
    parser.add_argument('--iphone', action='store_true', help='initialize empty Health/travel archives and upload credentials')
    args = parser.parse_args(argv)
    print(json.dumps(initialize(args.root, demo=args.demo, iphone=args.iphone), indent=2))


if __name__ == '__main__':
    main()
