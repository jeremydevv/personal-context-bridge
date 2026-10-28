"""Browser-backed refresh/status tools alongside the existing Canvas read tools."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from .canvas_browser import load_config, private_read


def config():
    path=os.environ.get('PERSONAL_CONTEXT_CANVAS_BROWSER_CONFIG',str(Path.home()/'.config/personal-context-bridge/canvas-browser.json'))
    return load_config(path)


def browser_status():
    try: settings=config()
    except FileNotFoundError:return {'configured':False,'state':'unconfigured'}
    except (OSError,ValueError):return {'configured':True,'state':'failed','error_code':'browser_configuration_invalid'}
    try:status=json.loads(private_read(settings['status_file'],65536))
    except FileNotFoundError:status={'state':'not_collected'}
    except (OSError,ValueError):status={'state':'failed','error_code':'browser_status_unavailable'}
    return {'configured':True,'account':settings['account'],'canvas_url':settings['base_url'],**status}


def register(mcp):
    from mcp.types import ToolAnnotations

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,idempotentHint=True,openWorldHint=False))
    def canvas_browser_status() -> dict:
        """Check Ubuntu Firefox-backed Canvas account, last successful ingestion and auth/coverage state. Browser accounts use this route independently of Mac token collection. Read with existing Canvas tools using the returned account label. A partial snapshot means some school resources are unavailable; authentication_required needs interactive browser sign-in. No credentials are returned."""
        return browser_status()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=True,openWorldHint=False))
    def refresh_canvas_browser() -> dict:
        """Request read-only Canvas collection from the configured Ubuntu Firefox login session, without requiring the Mac. Updates only the encrypted local archive. Returns queued, not completed; poll canvas_browser_status for a new last_success_at and coverage. Never sends messages, submits work, or marks conversations read. Sign in interactively if authentication_required."""
        settings=config()
        before=canvas_browser_status()
        requested_at=datetime.now(timezone.utc).isoformat()
        result=subprocess.run(['systemctl','--user','start','--no-block','personal-context-canvas-browser.service'],capture_output=True,timeout=15)
        return {'account':settings['account'],'state':'queued' if result.returncode==0 else 'failed',
                'requested_at':requested_at,'previous_last_success_at':before.get('last_success_at'),
                'collection_finished':False,'error_code':None if result.returncode==0 else 'browser_worker_unavailable',
                'check':'canvas_browser_status'}
