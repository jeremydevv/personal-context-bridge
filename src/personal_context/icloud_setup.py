"""Local-only setup/authentication CLI. Never run through an MCP tool."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
from .icloud_drive import Drive, DriveError


def prepare(drive):
    os.umask(0o077)
    drive.root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if drive.root.is_symlink() or drive.root.stat().st_mode & 0o077:
        raise DriveError('Private owner-only runtime directory required')
    if not drive.binary.is_file():raise DriveError('Install the pinned libfido2 Rclone build first')
    version=subprocess.run([str(drive.binary),'version'],env=drive.environment(),
                           capture_output=True,check=True,timeout=10).stdout
    if b'libfido2' not in version:raise DriveError('The Rclone binary lacks libfido2 support')
    # The helper gives Rclone only a purpose-derived password, never the archive key.
    helper = '''import hashlib,hmac,os,stat,sys
from pathlib import Path
p=Path(os.environ['PERSONAL_CONTEXT_KEY_FILE'])
s=p.lstat()
if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size!=32:
    sys.exit('Private unlocked archive key required')
k=p.read_bytes()
if len(k)!=32:sys.exit('Invalid archive key')
print(hmac.new(k,b'personal-context/icloud-drive/rclone-config/v1',hashlib.sha256).hexdigest())
'''
    if drive.password_command.exists() and drive.password_command.is_symlink():
        raise DriveError('Invalid password helper path')
    drive.password_command.write_text('#!'+sys.executable+' -I\n'+helper)
    drive.password_command.chmod(0o700)
    if not drive.config.exists():
        # Empty plaintext contains no account/session. Encrypt before accepting any login.
        with drive.config.open('x') as f:f.write('# Empty isolated iCloud configuration\n')
        drive.config.chmod(0o600)
        try:
            subprocess.run([str(drive.binary),'--config',str(drive.config),'--password-command',
                            str(drive.password_command),'--ask-password=false','config','encryption','set'],
                           env=drive.environment(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,check=True,timeout=15)
        except (OSError,subprocess.SubprocessError):
            drive.config.unlink(missing_ok=True)
            raise DriveError('Could not initialize encrypted config; unlock the archive key first') from None
    drive._require_config()
    return drive.status()


def key_status():
    """Enumerate FIDO devices without requesting assertions or PINs."""
    lib=ctypes.CDLL('libfido2.so.1')
    lib.fido_init(0)
    lib.fido_dev_info_new.argtypes=[ctypes.c_size_t]
    lib.fido_dev_info_new.restype=ctypes.c_void_p
    lib.fido_dev_info_manifest.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
    lib.fido_dev_info_ptr.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
    lib.fido_dev_info_ptr.restype=ctypes.c_void_p
    lib.fido_dev_info_path.argtypes=[ctypes.c_void_p]
    lib.fido_dev_info_path.restype=ctypes.c_char_p
    lib.fido_dev_info_free.argtypes=[ctypes.POINTER(ctypes.c_void_p),ctypes.c_size_t]
    pointer=ctypes.c_void_p(lib.fido_dev_info_new(64));count=ctypes.c_size_t()
    if not pointer:raise DriveError('FIDO device enumeration unavailable')
    try:
        if lib.fido_dev_info_manifest(pointer,64,ctypes.byref(count)):
            raise DriveError('FIDO device enumeration failed')
        devices=[]
        for index in range(count.value):
            raw=lib.fido_dev_info_path(lib.fido_dev_info_ptr(pointer,index))
            if raw:
                path=raw.decode();devices.append({'device':path,'accessible':os.access(path,os.R_OK|os.W_OK)})
        return {'fido_devices':devices,'key_present':bool(devices),
                'accessible_key':any(d['accessible'] for d in devices)}
    finally:lib.fido_dev_info_free(ctypes.byref(pointer),64)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','authenticate','reconnect','verify','status','check-key'))
    args=parser.parse_args(argv);drive=Drive()
    if args.action=='check-key':print(json.dumps(key_status(),indent=2));return
    if args.action=='prepare':print(json.dumps(prepare(drive),indent=2));return
    if args.action in ('status','verify'):
        result=drive.status(probe=args.action=='verify');print(json.dumps(result,indent=2))
        if args.action=='verify' and not result['live_access_verified']:raise SystemExit(1)
        return
    if not sys.stdin.isatty():raise DriveError('Authentication requires an interactive local terminal')
    prepare(drive)
    key=key_status()
    if not key['accessible_key']:
        print(json.dumps(key,indent=2))
        raise DriveError('Insert the registered USB key with user read/write access, then retry. No PIN was attempted.')
    print('Create remote icloud, choose iclouddrive, service drive. Use your registered USB security key.\n'
          'Enter account credentials/PIN only into this terminal. Keep the configuration encrypted.\n'
          'If prompted, approve web access on your trusted Apple device. No session transfer is performed.')
    command=['config'] if args.action=='authenticate' else ['config','reconnect','icloud:']
    with drive.lock():
        subprocess.run([str(drive.binary),'--config',str(drive.config),
                        '--password-command',str(drive.password_command),*command],
                       env=drive.environment(),check=True)
    drive._require_config()
    result=drive.status(probe=True);print(json.dumps(result,indent=2))
    if not result['live_access_verified']:raise SystemExit(1)


if __name__=='__main__':main()
