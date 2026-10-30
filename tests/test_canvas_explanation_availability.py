"""Optional explanations must not masquerade as source data or running work."""
import builtins
import sys
import unittest
from unittest.mock import patch

from personal_context.canvas_mcp_server import register_tools


class CanvasExplanationAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.functions = {}
        functions = self.functions

        class Registry:
            def tool(self, **kwargs):
                def capture(fn):
                    functions[fn.__name__] = fn
                    return fn
                return capture

        register_tools(Registry(), common_refresh=False)

    def test_missing_backend_reports_unsupported_for_every_explanation_read(self):
        with patch.dict(sys.modules, {'personal_context.summary_mcp': None}):
            for name, kwargs in (
                ('canvas_summary_status', {}),
                ('canvas_search_explanations', {}),
                ('canvas_search_explanations', {'kind': 'assignment'}),
                ('get_canvas_explanation', {'summary_id': 'fictional-summary'}),
            ):
                with self.subTest(tool=name, kwargs=kwargs):
                    result = self.functions[name](**kwargs)
                    self.assertIs(result.get('available'), False)
                    self.assertEqual(result.get('state'), 'unsupported_capability')
                    self.assertIn('search_canvas', result.get('alternative_tools', []))
                    self.assertNotIn('found', result)

    def test_missing_backend_does_not_claim_processing_enabled_by_environment(self):
        import os
        with patch.dict(sys.modules, {'personal_context.summary_mcp': None}):
            for enabled in ('0', '1'):
                with self.subTest(enabled=enabled), patch.dict(os.environ, PERSONAL_CONTEXT_CANVAS_EXTENDED_SUMMARIES=enabled):
                    result = self.functions['canvas_summary_status']()
                    self.assertEqual(result['new_canvas_processing'], 'unavailable')

    def test_backend_dependency_failure_is_not_reported_as_absent_backend(self):
        original_import = builtins.__import__

        def import_with_broken_backend(name, *args, **kwargs):
            if name == 'summary_mcp':
                raise ModuleNotFoundError("No module named 'fictional_backend_dependency'", name='fictional_backend_dependency')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=import_with_broken_backend):
            with self.assertRaisesRegex(ModuleNotFoundError, 'fictional_backend_dependency'):
                self.functions['canvas_summary_status']()
