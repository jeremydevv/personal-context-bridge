"""Opt-in read-only IMAP collection, separate from Apple local identity.

Credentials are supplied explicitly in a private file; Apple tokens/Keychain are
never inspected. Provider UIDs cannot replace Apple local IDs, so these batches
use a distinct source and incomplete snapshots (no legacy tombstones).
"""
import email.policy
import hashlib
import imaplib
import json
import os
import re
import ssl
import stat
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path


def _credential(path):
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError('IMAP needs an absolute protected credentials_file')
    # O_NOFOLLOW closes the symlink/stat-to-open race; inspect the opened inode.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 16384):
            raise ValueError('IMAP credentials must be owner-only regular file')
        credential = json.load(stream)
    if (not isinstance(credential, dict)
            or not isinstance(credential.get('username'), str) or not credential['username']
            or not (bool(isinstance(credential.get('password'), str) and credential['password'])
                        != bool(isinstance(credential.get('access_token'), str) and credential['access_token']))):
        raise ValueError('IMAP credentials need username and exactly one password or access_token')
    return credential


def _settings(config):
    options = config.get('headless', {}).get('mail', {})
    if options.get('mode') != 'imap':
        raise ValueError('direct provider Mail is not configured')
    host = options.get('host')
    port = options.get('port', 993)
    if not isinstance(host, str) or not host or any(c.isspace() for c in host):
        raise ValueError('IMAP needs explicit TLS provider host')
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError('IMAP port is invalid')
    mappings = options.get('mailboxes')
    selected = config.get('mailbox_urls', [])
    if not isinstance(mappings, list) or not mappings or not selected:
        raise ValueError('IMAP needs explicit selected-mailbox mappings')
    names, urls = set(), set()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise ValueError('IMAP mailbox mapping is invalid')
        name, url = mapping.get('name'), mapping.get('archive_mailbox_url')
        if (not isinstance(name, str) or not name or any(ord(c) < 32 or ord(c) > 126 for c in name)
                or not isinstance(url, str) or url not in selected or name in names or url in urls):
            raise ValueError('IMAP mappings must be unique and match selected mailbox URLs')
        names.add(name)
        urls.add(url)
    if urls != set(selected):
        raise ValueError('every selected Mail mailbox needs an explicit provider mapping')
    limit = config.get('limit', 50000)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50000:
        raise ValueError('invalid IMAP message limit')
    return options, mappings, limit


def _quoted(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _body(message):
    part = message.get_body(preferencelist=('plain', 'html'))
    if part is None:
        return ''
    content = part.get_content()
    if not isinstance(content, str):
        raise ValueError('IMAP message body is unsupported')
    return content


def _profile_batches(config, timestamp, recent=False):
    """Yield archive batch dictionaries; errors never include server responses.

    Recent means a three-day server SINCE scan. Neither mode issues STORE,
    EXPUNGE, CLOSE, CREATE, MOVE or SELECT without EXAMINE/read-only semantics.
    """
    options, mappings, limit = _settings(config)
    credential = _credential(options.get('credentials_file'))
    client = None
    try:
        client = imaplib.IMAP4_SSL(options['host'], options.get('port', 993),
                                  ssl_context=ssl.create_default_context(), timeout=60)
        if credential.get('access_token'):
            username, token = credential['username'], credential['access_token']
            if any(c in username + token for c in ('\x00', '\x01', '\r', '\n')):
                raise ValueError('invalid IMAP OAuth credential encoding')
            auth = ('user=' + username + '\x01auth=Bearer ' + token + '\x01\x01').encode()
            status = client.authenticate('XOAUTH2', lambda challenge: auth if not challenge else b'')[0]
        else:
            status = client.login(credential['username'], credential['password'])[0]
        if status != 'OK':
            raise RuntimeError('IMAP authentication failed')
        for mapping in mappings:
            if client.select(_quoted(mapping['name']), readonly=True)[0] != 'OK':
                raise RuntimeError('selected IMAP mailbox is unavailable')
            response, validity = client.response('UIDVALIDITY')
            if response != 'UIDVALIDITY' or not validity or not re.fullmatch(rb'[1-9][0-9]*', validity[0]):
                raise ValueError('IMAP mailbox lacks stable UIDVALIDITY')
            criterion = 'ALL'
            if recent:
                since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%d-%b-%Y')
                criterion = 'SINCE ' + since
            status, found = client.uid('SEARCH', None, criterion)
            if status != 'OK' or len(found) != 1 or not isinstance(found[0], bytes):
                raise RuntimeError('IMAP search failed')
            uids = found[0].split()
            if len(uids) >= limit or len(set(uids)) != len(uids) or any(not re.fullmatch(rb'[1-9][0-9]*', uid) for uid in uids):
                raise ValueError('IMAP mailbox is incomplete or reached its limit')
            buckets = [[] for _ in range(32)]
            # Include host/account as hashes: UIDs from another account cannot
            # overwrite records if the configured account is changed later.
            account = hashlib.sha256((options['host'] + '\0' + credential['username']).encode()).hexdigest()
            for uid in uids:
                status, data = client.uid('FETCH', uid.decode('ascii'), '(UID BODY.PEEK[])')
                parts = [part for part in data if isinstance(part, tuple)] if isinstance(data, list) else []
                if (status != 'OK' or len(parts) != 1 or not isinstance(parts[0][1], bytes)
                        or not re.search(rb'\bUID ' + uid + rb'\b', parts[0][0])):
                    raise ValueError('IMAP fetch did not return the exact requested UID')
                message = BytesParser(policy=email.policy.default).parsebytes(parts[0][1])
                body = _body(message)
                sender = getaddresses(message.get_all('From', []))
                to = [{'name': name, 'address': address} for name, address in getaddresses(message.get_all('To', []))]
                cc = [{'name': name, 'address': address} for name, address in getaddresses(message.get_all('Cc', []))]
                date = None
                if message.get('Date'):
                    try:
                        parsed = parsedate_to_datetime(message['Date'])
                        date = parsed.isoformat() if parsed.tzinfo else None
                    except (ValueError, TypeError, OverflowError):
                        pass
                identifier = '|'.join((account, mapping['archive_mailbox_url'], validity[0].decode(), uid.decode()))
                payload = {'messageId': str(message.get('Message-ID', '')), 'subject': str(message.get('Subject', '')),
                           'senderAddress': sender[0][1] if sender else '', 'to': to, 'cc': cc,
                           'content': body, 'contentAvailable': True, 'archiveMailboxUrl': mapping['archive_mailbox_url'],
                           'providerFreshness': 'server-read', 'identity': 'imap-uid', 'uid': uid.decode(),
                           'uidValidity': validity[0].decode()}
                record = {'id': identifier, 'title': payload['subject'] or '(no subject)',
                          'body': '\n'.join([payload['senderAddress']] + [x['address'] for x in to + cc] + [body]),
                          'start': date, 'end': None, 'payload': payload}
                bucket = int.from_bytes(hashlib.sha256(identifier.encode()).digest()[:4], 'big') % 32
                buckets[bucket].append(record)
            for index, records in enumerate(buckets):
                if records or (not uids and index == 0):
                    yield {'schema': 1, 'source': 'provider-imap', 'kind': 'mail',
                           'scope': 'imap:' + account + ':' + mapping['archive_mailbox_url'] + ':bucket:' + str(index),
                           'collected_at': timestamp, 'complete': False, 'records': records}
        # LOGOUT doesn't expunge; deliberately don't call IMAP.close().
    except (imaplib.IMAP4.error, OSError, UnicodeError) as exc:
        raise RuntimeError('IMAP collection failed; check provider access and selected-mailbox configuration') from None
    finally:
        if client is not None:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass


def provider_mail_batches(config, timestamp, recent=False):
    """Collect explicit provider profiles after acknowledging separate identities.

    Until a verified alias migration exists, enabling this adapter creates
    provider records alongside legacy Apple local copies. The explicit identity
    acknowledgement prevents treating this as a seamless destructive switch.
    """
    options = config.get('headless', {}).get('mail', {})
    if options.get('mode') != 'imap':
        raise ValueError('direct provider Mail is not configured')
    if options.get('identity_migration_acknowledged') is not True:
        raise ValueError('direct Mail requires explicit identity_migration_acknowledged; provider UIDs coexist with Apple local IDs')
    profiles = options.get('profiles', [options])
    if not isinstance(profiles, list) or not profiles:
        raise ValueError('IMAP requires configured provider profiles')
    urls = []
    prepared = []
    for profile in profiles:
        if not isinstance(profile, dict) or 'profiles' in profile and profile is not options:
            raise ValueError('invalid IMAP provider profile')
        mappings = profile.get('mailboxes', [])
        if not isinstance(mappings, list):
            raise ValueError('invalid IMAP provider mailbox mappings')
        selected = [item.get('archive_mailbox_url') for item in mappings if isinstance(item, dict)]
        urls.extend(selected)
        child = dict(config, mailbox_urls=selected, headless={'mail': dict(profile, mode='imap')})
        # Validate every profile and credential before making the first network request.
        _settings(child)
        _credential(profile.get('credentials_file'))
        prepared.append(child)
    if len(urls) != len(set(urls)) or set(urls) != set(config.get('mailbox_urls', [])):
        raise ValueError('provider profiles must cover every selected mailbox exactly once')
    for child in prepared:
        yield from _profile_batches(child, timestamp, recent)
