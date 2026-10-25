"""Common refresh tools; registration and read status never start collection."""
import os

SOURCES = ('calendar', 'reminder', 'contact', 'mail', 'message', 'note',
           'voice_memo', 'canvas', 'obsidian', 'saved_video', 'health',
           'location', 'google_timeline', 'icloud_drive', 'summaries')


def _scope(source):
    if source != 'all' and source not in SOURCES:
        raise ValueError('unsupported data source')
    return source


def source_status(source='all', database=None):
    """Return tracking without inferring live collection from archive timestamps."""
    _scope(source)
    try:
        from .refresh_tracking import source_status as read_status
        return read_status(source, database=database)
    except Exception:
        # A locked/uninstalled ledger must not hide readable source archives or
        # disclose private configuration paths through an exception string.
        names = SOURCES if source == 'all' else (source,)
        return {'status': 'unavailable', 'configured': False,
                'sources': {name: {'capability': {'health': 'waiting_for_device', 'location': 'waiting_for_device',
                                                'google_timeline': 'manual_import_required', 'icloud_drive': 'requires_auth',
                                                'summaries': 'derived_processing'}.get(name, 'unconfigured'),
                                  'refresh': {'state': 'unavailable'},
                                  'source_freshness': {'state': 'unknown'},
                                  'ingestion': {'state': 'unknown'},
                                  'summary': {'state': 'unknown'}} for name in names}}


def with_tracking(result, source='all', database=None):
    return {**result, 'data_refresh': source_status(source, database)}


def request(sources=None, mode='recent', source='all'):
    """Validate the app scope before creating durable work."""
    _scope(source)
    if os.environ.get('PERSONAL_CONTEXT_REFRESH_ENABLED') != '1':
        raise ValueError('data refresh requests are disabled')
    requested = list(sources or ([] if source == 'all' else [source]))
    if any(name not in SOURCES for name in requested):
        raise ValueError('unsupported data source')
    if source != 'all' and any(name != source for name in requested):
        raise ValueError('this app can refresh only its own source')
    if mode not in ('recent', 'full'):
        raise ValueError('mode must be recent or full')
    try:
        from .refresh_tracking import request_refresh
        return request_refresh(requested, mode=mode)
    except ValueError as error:
        if str(error) == 'no enabled refresh sources':
            raise ValueError('no enabled refresh sources') from None
        raise ValueError('refresh request unavailable; check private configuration') from None
    except Exception:
        raise ValueError('refresh request unavailable; check private configuration') from None


def status(refresh_id, source='all'):
    _scope(source)
    try:
        from .refresh_tracking import refresh_status
        result = refresh_status(refresh_id)
    except Exception:
        return {'refresh_id': refresh_id, 'state': 'unavailable', 'requested': False}
    if source != 'all' and 'sources' in result:
        if source not in result['sources']:
            raise ValueError('refresh does not include this source')
        child = result['sources'][source]
        result = {**result, 'sources': {source: child}, 'state': child.get('state', 'unknown')}
    return result


def _scoped_state(children):
    states = [child.get('state', 'unknown') for child in children.values()]
    if all(state == 'complete' for state in states):
        return 'complete'
    for state in ('running', 'queued', 'waiting', 'interrupted'):
        if state in states:
            return state
    return 'partial' if any(state in ('complete', 'partial') for state in states) else 'failed'


def compatibility(kind, record_id, source='all', database=None):
    """Read-only routes for clients whose cached catalog lacks common tools."""
    if kind == 'data_refresh_status':
        return status(record_id, source)
    if kind == 'data_source_status':
        selected = record_id or source
        if source != 'all' and selected not in ('all', source):
            raise ValueError('this app can read only its own source status')
        return source_status(source if selected == 'all' else selected, database)
    raise ValueError('unsupported tracking record kind')


def register(mcp, source='all', database=None, allowed_sources=None):
    from mcp.types import ToolAnnotations
    _scope(source)
    allowed = tuple(allowed_sources or (SOURCES if source == "all" else (source,)))
    for name in allowed:
        _scope(name)
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                           idempotentHint=True, openWorldHint=False)

    @mcp.tool(annotations=read)
    def data_source_status(source: str = 'all') -> dict:
        """Report configured collection capabilities and durable refresh state. Source freshness, correlated archive ingestion and derived summaries are separate. Push-only/manual/unconfigured sources cannot be forced current. Reading status never requests work."""
        if source != 'all' and source not in allowed:
            raise ValueError('this app can read only its own source status')
        if source != 'all':
            return source_status(source, database)
        if scope == 'all':
            return source_status('all', database)
        if len(allowed) == 1:
            return source_status(scope, database)
        snapshots = {name: source_status(name, database) for name in allowed}
        return {'configured': any(snapshot.get('configured', False) for snapshot in snapshots.values()),
                'sources': {name: snapshot.get('sources', {}).get(name, {})
                            for name, snapshot in snapshots.items()}}

    @mcp.tool(annotations=read)
    def data_refresh_status(refresh_id: str) -> dict:
        """Read a durable refresh request by ID. Queued/accepted work is not completion; only correlated archive acknowledgement establishes ingestion. Errors and device/provider limitations remain explicit."""
        if len(allowed) == 1:
            return status(refresh_id, scope)
        result = status(refresh_id)
        if scope != 'all' and 'sources' in result:
            selected = {name: child for name, child in result['sources'].items() if name in allowed}
            if not selected:
                raise ValueError('refresh does not include this app sources')
            result = {**result, 'sources': selected, 'state': _scoped_state(selected)}
        return result

    scope = source
    if os.environ.get('PERSONAL_CONTEXT_REFRESH_ENABLED') == '1':
        write = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                               idempotentHint=False, openWorldHint=False)

        @mcp.tool(annotations=write)
        def request_data_refresh(sources: list[str] = None, mode: str = 'recent') -> dict:
            """Queue durable source collection; returns refresh_id for data_refresh_status. Omit sources for this app's source, or configured enabled sources on the main app. Source apps cannot request other sources. Acceptance is not collection or ingestion; this does not send or edit native records. Requires refresh opt-in."""
            selected = list(sources or ([] if scope == 'all' else allowed))
            if any(name not in allowed for name in selected):
                raise ValueError('this app can refresh only its own sources')
            return request(selected, mode)
