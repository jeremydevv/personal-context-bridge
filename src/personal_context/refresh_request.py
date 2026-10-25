"""Approval-gated requests for fixed collection jobs; acceptance is not completion."""

import os
import re
import subprocess


MAC_JOBS = {
    "apple": "org.personalcontext.personal-context-fast-sync",
    "canvas": "org.personalcontext.personal-context-canvas-sync",
}
OBSIDIAN_UNIT = "obsidian-icloud-sync.service"


def request_mac_refresh(job, target=None):
    if job not in MAC_JOBS: raise ValueError('unsupported refresh job')
    from .refresh_tracking import request_refresh
    return request_refresh(['canvas'] if job=='canvas' else ['calendar','reminder','contact','mail','message','note','voice_memo'])


def request_obsidian_refresh():
    from .refresh_tracking import request_refresh
    return request_refresh(['obsidian'])
