"""Refresh classifications are not native iCloud authentication observations."""
import tempfile
import unittest
from unittest.mock import patch
from personal_context import refresh_mcp, refresh_tracking
from personal_context.subscription_auth import PrivateState


class ICloudRefreshStatusHonestyTests(unittest.TestCase):
    def assert_not_probed(self, entry):
        self.assertEqual(entry['capability'], 'requires_auth')
        self.assertEqual(entry.get('capability_scope'), 'refresh_coordination')
        self.assertEqual(entry.get('native_authentication'), 'not_checked')
        self.assertEqual(entry.get('native_access'), 'not_checked')
        self.assertIn('not an authentication probe', entry.get('readiness_note', ''))

    def test_configured_refresh_status_does_not_infer_native_auth(self):
        with tempfile.TemporaryDirectory() as root:
            coordinator = refresh_tracking.Coordinator(PrivateState(root, b'x' * 32),
                {'sources': {'icloud_drive': {'enabled': False}}})
            entry = coordinator.sources('icloud_drive')['sources']['icloud_drive']
            self.assertFalse(entry['enabled'])
            self.assert_not_probed(entry)

    def test_unconfigured_refresh_status_does_not_infer_native_auth(self):
        with patch.object(refresh_tracking, 'coordinator', side_effect=KeyError('fixture')):
            self.assert_not_probed(refresh_tracking.source_status('icloud_drive')['sources']['icloud_drive'])

    def test_unavailable_mcp_fallback_does_not_infer_native_auth(self):
        with patch.object(refresh_tracking, 'source_status', side_effect=RuntimeError('private fixture')):
            result = refresh_mcp.source_status('icloud_drive')
        self.assertEqual(result['status'], 'unavailable')
        self.assert_not_probed(result['sources']['icloud_drive'])
        self.assertNotIn('private fixture', str(result))

    def test_other_source_contract_is_unchanged(self):
        with patch.object(refresh_tracking, 'coordinator', side_effect=KeyError('fixture')):
            entry = refresh_tracking.source_status('health')['sources']['health']
        self.assertEqual(entry['capability'], 'waiting_for_device')
        self.assertNotIn('native_authentication', entry)
