"""Pure explanations of refresh metadata, never live readiness probes."""


def source_readiness_metadata(source):
    if source != 'icloud_drive':
        return {}
    return {
        'capability_scope': 'refresh_coordination',
        'native_authentication': 'not_checked',
        'native_access': 'not_checked',
        'readiness_note': (
            'Refresh capability and enabled describe refresh coordination, not an authentication probe. '
            'Native Mac connection readiness is separate from experimental Rclone setup. '
            'Use icloud_drive_status(probe=false) for setup metadata; live access remains unverified.'
        ),
    }
