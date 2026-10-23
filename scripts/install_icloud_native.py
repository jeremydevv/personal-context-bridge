#!/usr/bin/env python3
"""Run on the Mac: prepare the disabled native endpoint; never scan iCloud."""
import json
import os
from pathlib import Path
import shutil
import sys

if sys.platform!='darwin':raise SystemExit('Run this installer on the Mac')
source=Path(__file__).resolve().parents[1]/'src/personal_context/icloud_native.py'
runtime=Path.home()/'.local/share/personal-context-bridge/icloud-native'
runtime.mkdir(mode=0o700,parents=True,exist_ok=True);runtime.chmod(0o700)
module=runtime/'receiver.py';shutil.copyfile(source,module);module.chmod(0o600)
bin_dir=runtime.parent/'bin';bin_dir.mkdir(mode=0o700,exist_ok=True)
command=bin_dir/'icloud-drive-receiver'
# The interpreter and module are installation-controlled, never request text.
import shlex
command.write_text('#!/bin/sh\nexec '+shlex.quote(str(Path(sys.executable).resolve()))+' -I '+shlex.quote(str(module))+'\n')
command.chmod(0o700)
config=Path.home()/'.config/personal-context-bridge/icloud-native.json'
config.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
if not config.exists():
    fd=os.open(config,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as out:
        json.dump({'enabled':False,'permission':'writer','root':str(Path.home()/'Library/Mobile Documents/com~apple~CloudDocs'),
                   'segments':{'drive':''}},out,indent=2)
print('Native endpoint prepared; connection remains disabled. No iCloud files inspected.')
