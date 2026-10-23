"""Fictional note fixtures: granular summaries must retain exact evidence."""
import hashlib
import unittest

from personal_context.note_summary_units import note_summary_units, DENSE_NOTE_PROMPT


def record(identity, text):
    return dict(id=identity, title=identity.rsplit('/', 1)[-1], body=text,
                digest=hashlib.sha256(text.encode()).hexdigest(),
                reference=dict(tool='obsidian_read_note', vault='Example', path=identity))


class NoteSummaryUnitsTests(unittest.TestCase):
    def units(self, text, **kwargs):
        return list(note_summary_units([record('Research.md', text)], **kwargs))

    def assert_coverage(self, text, units):
        end = 0
        for unit in units:
            self.assertEqual(len(unit['refs']), 1)
            ref = unit['refs'][0]
            self.assertEqual(ref['offset'], end)
            self.assertEqual(unit['input']['items'][0]['text'], text[end:ref['end_offset']])
            self.assertLessEqual(ref['end_offset'] - end, 1000)
            end = ref['end_offset']
        self.assertEqual(end, len(text))

    def test_notes_are_never_merged_and_ids_ignore_other_notes(self):
        a, b = record('A.md', 'Fee: $42; projected, not approved.'), record('B.md', 'Fee: $18.')
        first = list(note_summary_units([a]))
        both = list(note_summary_units([b, a]))
        self.assertEqual(len(both), 2)
        self.assertEqual(first[0], both[1])
        self.assertNotEqual(both[0]['id'], both[1]['id'])

    def test_short_note_stays_whole_with_locator(self):
        unit = self.units('# Plan\nBudget: $42.\n')[0]
        self.assertEqual(unit['input']['locator']['path'], 'Research.md')
        self.assertEqual(unit['input']['locator']['start_line'], 1)
        self.assertEqual(unit['input']['locator']['end_line'], 2)
        self.assertEqual(unit['input']['granularity'], 'note')

    def test_long_note_splits_at_nested_headings_with_exact_offsets(self):
        text = '# Project\n' + ('x' * 700) + '\n## Costs\nFee: $42.\n' + ('y' * 700) + '\n## Risks\nNot approved.\n'
        units = self.units(text, max_chars=1000)
        self.assert_coverage(text, units)
        self.assertEqual([u['input']['locator']['heading_path'] for u in units],
                         [['Project'], ['Project', 'Costs'], ['Project', 'Risks']])
        self.assertEqual(units[1]['input']['locator']['start_line'], 3)

    def test_frontmatter_fences_and_setext_are_not_confused(self):
        text = '---\ntitle: Example\n---\nIntro\n' + ('p' * 1000) + '\n\n```md\n# Fake\n```\n\nReal heading\n============\nDetails\n'
        units = self.units(text, max_chars=1000)
        self.assert_coverage(text, units)
        paths = [u['input']['locator']['heading_path'] for u in units]
        self.assertNotIn(['Fake'], paths)
        self.assertEqual(paths[-1], ['Real heading'])
        self.assertIn('title: Example', ''.join(u['input']['items'][0]['text'] for u in units))

    def test_large_section_unicode_crlf_and_no_trailing_newline(self):
        text = '# Numbers\r\n' + ('☃: 123.45 kg\r\n' * 200) + 'final'
        units = self.units(text, max_chars=1000)
        self.assert_coverage(text, units)
        for unit in units:
            ref = unit['refs'][0]
            locator = unit['input']['locator']
            self.assertEqual(locator['start_line'], text.count('\n', 0, ref['offset']) + 1)
            self.assertEqual(locator['end_line'], text.count('\n', 0, max(ref['offset'], ref['end_offset'] - 1)) + 1)

    def test_repeated_headings_are_distinct(self):
        text = '# Same\n' + ('x' * 700) + '\n# Same\n' + ('y' * 700)
        units = self.units(text, max_chars=1000)
        self.assert_coverage(text, units)
        self.assertEqual(len({u['id'] for u in units}), len(units))

    def test_empty_note_retains_reference(self):
        units = self.units('')
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['refs'][0]['end_offset'], 0)

    def test_edit_invalidates_digest_but_keeps_identity(self):
        a, b = self.units('Cost $42.'), self.units('Cost $43.')
        self.assertEqual(a[0]['id'], b[0]['id'])
        self.assertNotEqual(a[0]['digest'], b[0]['digest'])

    def test_bounds_and_dense_prompt_constraints(self):
        for size in (0, 999, 20001):
            with self.assertRaises(ValueError): self.units('text', max_chars=size)
        for requirement in ('numbers', 'exceptions', 'source_index', 'untrusted', '20 facts'):
            self.assertIn(requirement, DENSE_NOTE_PROMPT)
