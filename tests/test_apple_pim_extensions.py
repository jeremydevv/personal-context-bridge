import base64
import hashlib
import unittest
from personal_context.apple_write_queue import validate_payload


def file_spec(data=b'%PDF-1.4\nfictional fixture', name='fixture.pdf', mime='application/pdf'):
    return dict(filename=name, media_type=mime, content_base64=base64.b64encode(data).decode(),
                sha256=hashlib.sha256(data).hexdigest())


class ExtensionTests(unittest.TestCase):
    def edit(self, kind, changes):
        fields = dict(operation='update_private', item_id='native-id', expected_revision='a'*64, changes=changes)
        if kind == 'calendar': fields.update(occurrence_start_at='2031-11-01T17:00:00Z', scope='this')
        return validate_payload(kind, fields)

    def test_native_tags_support_replace_add_remove_and_clear(self):
        for changes in ({'set_tags':['work', 'focus']}, {'set_tags':[]},
                        {'add_tags':['work'], 'remove_tags':['old']}):
            self.assertEqual(self.edit('reminder', changes)['changes'], changes)
        for changes in ({'set_tags':['work'], 'add_tags':['new']}, {'add_tags':['x','x']},
                        {'add_tags':['bad tag']}, {'set_tags':['#fake']}, {'remove_tags':[]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.edit('reminder', changes)

    def test_attendee_operations_require_explicit_invitation_consent(self):
        fields = {'add_attendees':[{'email':'person@example.com', 'name':'Fictional Person'}],
                  'allow_invitation_delivery':True}
        self.assertEqual(self.edit('calendar', fields)['changes'], fields)
        self.edit('calendar', {'remove_attendees':['person@example.com'], 'allow_invitation_delivery':True})
        for patch in ({'add_attendees':[{'email':'person@example.com'}]},
                      {'add_attendees':[{'email':'bad\n@example.com'}], 'allow_invitation_delivery':True},
                      {'remove_attendees':['person@example.com'], 'allow_invitation_delivery':False}):
            with self.subTest(patch=patch), self.assertRaises(ValueError): self.edit('calendar', patch)

    def test_attachments_accept_only_bounded_hashed_bytes_not_paths(self):
        for kind in ('calendar', 'reminder'):
            spec = file_spec() if kind == 'calendar' else file_spec(b'\x89PNG\r\n\x1a\nfixture', 'fixture.png', 'image/png')
            value = self.edit(kind, {'add_attachments':[spec]})
            self.assertEqual(validate_payload(kind, value), value)
            self.edit(kind, {'remove_attachments':['native-attachment-id']})
            for spec in (file_spec(name='../secret.pdf'), file_spec() | {'sha256':'0'*64},
                         file_spec() | {'path':'/private/file'}, file_spec(data=b'not a pdf'),
                         file_spec(data=b'x'*(2*1024*1024+1))):
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    self.edit(kind, {'add_attachments':[spec]})
        with self.assertRaises(ValueError): self.edit('reminder', {'add_attachments':[file_spec()]})

    def test_attachment_types_and_cross_source_fields_fail_cleanly(self):
        for media_type in (None, {}, [], 1):
            with self.subTest(media_type=media_type), self.assertRaises(ValueError):
                self.edit('calendar', {'add_attachments':[file_spec() | {'media_type':media_type}]})
        for kind, patch in (('calendar', {'set_tags':['work']}),
                            ('reminder', {'add_attendees':[{'email':'person@example.com'}],
                                          'allow_invitation_delivery':True})):
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.edit(kind, patch)
