"""Mac-only disposable native metadata tests; never sends invitations."""
import base64
import argparse
import hashlib
import subprocess
import uuid
from personal_context.mac_pim_executor import _bridge
from personal_context.apple_write_queue import validate_payload


def pdf_fixture():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> >>']
    data = b'%PDF-1.4\n'
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    position = len(data)
    data += b'xref\n0 4\n0000000000 65535 f \n'
    data += b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets[1:])
    return data + f'trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{position}\n%%EOF\n'.encode()


def spec(data, name, mime):
    return dict(filename=name, media_type=mime, content_base64=base64.b64encode(data).decode(), sha256=hashlib.sha256(data).hexdigest())


def call(kind, fields):
    result = _bridge(kind, fields, subprocess.run)
    assert result.get('success') is True, result
    return result


def main(sources=('calendar', 'reminder')):
    suffix = uuid.uuid4().hex[:10]
    start = '2031-11-06T17:00:00Z'
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
    fixtures = [spec(png, 'fictional.png', 'image/png'), spec(pdf_fixture(), 'fictional.pdf', 'application/pdf')]
    for kind in sources:
        inventory = call(kind, {'operation':'destinations'})['destinations']
        target = next(d['id'] for d in inventory if d['writable'] and d['account'].casefold() == 'icloud')
        fields = dict(title='Personal Context native extensions synthetic ' + suffix, notes='Fictional validation item', alerts=[])
        if kind == 'calendar': fields.update(start_at=start, end_at='2031-11-06T18:00:00Z', calendar=target)
        else: fields.update(due_at=start, list_name=target)
        result = _bridge(kind, validate_payload(kind, fields), subprocess.run)
        item = result.get('item_id')
        assert item, result
        def inspect():
            request = dict(operation='inspect', item_id=item)
            if kind == 'calendar': request['occurrence_start_at'] = start
            return call(kind, request)
        def edit(changes, operation='update_private'):
            current = inspect()
            request = dict(operation=operation, item_id=item, expected_revision=current['revision'])
            if changes is not None: request['changes'] = changes
            if kind == 'calendar': request.update(occurrence_start_at=start, scope='this')
            result = _bridge(kind, validate_payload(kind, request), subprocess.run)
            if result.get('success') is not True: print('Failure metadata:', inspect()['item']['private_metadata'])
            assert result.get('success') is True, result
            return result
        try:
            assert result.get('verified'), result
            metadata = inspect()['item']['private_metadata']
            print(kind + ': capabilities ' + str({k:v for k,v in metadata.items() if k.startswith('supports_')}))
            if kind == 'reminder':
                assert metadata['supports_tags']
                edit({'set_tags':['synthetic', 'keep']})
                edit({'add_tags':['new'], 'remove_tags':['synthetic']})
                assert set(inspect()['item']['private_metadata']['tags']) == {'keep', 'new'}
                edit({'set_tags':[]})
                assert inspect()['item']['private_metadata']['tags'] == []
            batch = fixtures if kind == 'calendar' else fixtures[:1]
            edit({'add_attachments':batch})
            metadata = inspect()['item']['private_metadata']
            assert {x['sha256'] for x in metadata['attachments']} == {f['sha256'] for f in batch}, metadata
            ids = [x['attachment_id'] for x in metadata['attachments']]
            edit({'remove_attachments':[ids[0]]})
            remaining = inspect()['item']['private_metadata']['attachments']
            assert len(remaining) == len(ids)-1
            if remaining: edit({'remove_attachments':[x['attachment_id'] for x in remaining]})
            assert inspect()['item']['private_metadata']['attachments'] == []
            if kind == 'calendar':
                # Consent rejection occurs before any native mutation or invitation.
                current = inspect()
                rejected = _bridge(kind, dict(operation='update_private', item_id=item,
                    occurrence_start_at=start, scope='this', expected_revision=current['revision'],
                    changes={'add_attendees':[{'email':'nobody@example.invalid'}]}), subprocess.run)
                assert rejected.get('success') is False and rejected.get('write_started') is False, rejected
            print(kind + ': native tags/attachment byte readback and removal checks passed')
        finally:
            edit(None, operation='delete')
            print(kind + ': fictional native item removed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', choices=['calendar', 'reminder'])
    args = parser.parse_args()
    main((args.source,) if args.source else ('calendar', 'reminder'))
