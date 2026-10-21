"""One protected ChatGPT-plan session shared by all enrichment consumers.

Uses the documented public-client SIWC flow, never existing Codex credentials.
No token values or OAuth callback queries may be logged.
"""
from __future__ import annotations
import base64
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from urllib.parse import urlencode
import uuid

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ISSUER = 'https://auth.openai.com'
TOKEN_URL = ISSUER + '/api/accounts/oauth/token'
RESOURCE = 'https://api.openai.com/v1'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'


class SignInRequired(RuntimeError):
    pass


class PrivateState:
    """Authenticated encrypted JSON with atomic durable replacement and process locks."""
    def __init__(self, root, key):
        self.root = Path(root)
        if self.root.is_symlink() or len(key) != 32:
            raise ValueError('private runtime directory and 32-byte key required')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.cipher = AESGCM(hmac.digest(key, b'context-enrichment-state-v1', 'sha256'))

    @classmethod
    def from_env(cls):
        path = Path(os.environ['PERSONAL_CONTEXT_KEY_FILE'])
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('private archive key required')
        root = os.environ.get('PERSONAL_CONTEXT_ENRICHMENT_DIR', str(Path.home()/'.local/share/personal-context-enrichment'))
        return cls(root, path.read_bytes())

    def path(self, name, suffix='.enc'):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', name):
            raise ValueError('invalid state name')
        path = self.root / (name + suffix)
        if path.is_symlink():
            raise ValueError('state cannot be a symlink')
        return path

    @contextlib.contextmanager
    def lock(self, name):
        fd = os.open(self.path(name, '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def read(self, name, default=None):
        path = self.path(name)
        if not path.exists():
            return default
        raw = path.read_bytes()
        return json.loads(self.cipher.decrypt(raw[:12], raw[12:], name.encode()))

    def write(self, name, value):
        nonce = os.urandom(12)
        data = nonce + self.cipher.encrypt(nonce, json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), name.encode())
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix='.pending-')
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.path(name))
            dfd = os.open(self.root, os.O_DIRECTORY)
            try: os.fsync(dfd)
            finally: os.close(dfd)
        finally:
            Path(tmp).unlink(missing_ok=True)


class AuthSession:
    def __init__(self, state=None, http=None):
        self.state = state or PrivateState.from_env()
        self.http = http or httpx.Client(timeout=30, follow_redirects=False)
        with self.state.lock('auth'):
            if not self.state.read('host'):
                self.state.write('host', {'id': 'urn:uuid:' + str(uuid.uuid4())})

    def status(self):
        saved = self.state.read('session', {})
        return {'authenticated':bool(saved.get('access_token')), 'plan_usage_enabled':'chatgpt.tokens.use.direct' in saved.get('scopes',[]),
                'expires_at':saved.get('expires_at'), 'provider':'ChatGPT plan',
                'sign_in_required':not bool(saved.get('refresh_token'))}

    def begin(self, port=8794):
        with self.state.lock('auth'):
            saved = self.state.read('session', {})
            verifier = secrets.token_urlsafe(48)
            pending = {'state':secrets.token_urlsafe(32), 'nonce':secrets.token_urlsafe(32),
                       'verifier':verifier, 'redirect_uri':f'http://127.0.0.1:{port}/auth/callback',
                       'expires_at':time.time()+600,'client_id':saved.get('client_id','dynamic_agent_client'),
                       'subject':saved.get('subject')}
            self.state.write('pending', pending)
            params = {'client_id':pending['client_id'],'ext_agent_host_id':self.state.read('host')['id'],
                      'response_type':'code','redirect_uri':pending['redirect_uri'],'scope':SCOPES,
                      'resource':RESOURCE,'state':pending['state'],'nonce':pending['nonce'],
                      'code_challenge_method':'S256', 'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
            if pending['client_id'] == 'dynamic_agent_client': params['agent_name_hint']='Personal Context Bridge'
            elif saved.get('id_token'): params['id_token_hint']=saved['id_token']
            return ISSUER + '/api/accounts/authorize?' + urlencode(params)

    def validate_identity(self, token, client_id, nonce):
        import jwt
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256':
            raise ValueError('unexpected identity signing algorithm')
        keys = self.http.get(ISSUER+'/.well-known/jwks.json')
        keys.raise_for_status()
        matching = [k for k in keys.json()['keys'] if k.get('kid') == header.get('kid')]
        if len(matching) != 1: raise ValueError('unknown identity signing key')
        claims = jwt.decode(token, jwt.PyJWK.from_dict(matching[0]).key, algorithms=['RS256'],
                            issuer=ISSUER, audience=client_id, options={'require':['exp','iat','sub','iss','aud','nonce']})
        if not hmac.compare_digest(str(claims['nonce']), nonce): raise ValueError('identity nonce mismatch')
        return claims

    def complete(self, query):
        with self.state.lock('auth'):
            p = self.state.read('pending', {})
            if not p or p['expires_at'] < time.time() or not hmac.compare_digest(p['state'], str(query.get('state',''))):
                raise ValueError('expired or invalid sign-in state; start sign-in again')
            self.state.write('pending', {})  # single use; never log callback/code
            if query.get('error'): raise SignInRequired('Sign-in was declined; start again when ready')
            client_id = query.get('client_id', p['client_id'])
            if client_id == 'dynamic_agent_client' or not client_id or (p['client_id'] != 'dynamic_agent_client' and client_id != p['client_id']):
                raise ValueError('issued client identity missing or mismatched')
            response = self.http.post(TOKEN_URL, data={'grant_type':'authorization_code','client_id':client_id,
                                     'code':query.get('code',''),'code_verifier':p['verifier'],
                                     'redirect_uri':p['redirect_uri'],'resource':RESOURCE})
            if response.status_code != 200: raise SignInRequired('Code exchange failed; start a new sign-in')
            tokens = response.json()
            if not tokens.get('refresh_token'):
                raise SignInRequired('Offline access permission is required for shared background summaries')
            identity = self.validate_identity(tokens['id_token'], client_id, p['nonce'])
            if p.get('subject') and identity['sub'] != p['subject']: raise ValueError('selected account changed')
            self._save(tokens, {'client_id':client_id,'subject':identity['sub'],'email':identity.get('email'),
                               'ext_agent_host_id':self.state.read('host')['id']})
            return self.status()

    def _save(self, tokens, previous):
        scopes = tokens.get('scope', ' '.join(previous.get('scopes',[]))).split()
        if 'chatgpt.tokens.use.direct' not in scopes or not tokens.get('access_token'):
            raise SignInRequired('ChatGPT plan usage permission required')
        if str(tokens.get('token_type','Bearer')).lower() != 'bearer': raise ValueError('unexpected token type')
        saved=dict(previous)
        saved.update(tokens)
        saved.update(scopes=scopes,expires_at=time.time()+int(tokens.get('expires_in',3600)))
        self.state.write('session', saved)

    def token(self):
        with self.state.lock('auth'):
            saved = self.state.read('session', {})
            if not saved.get('refresh_token'): raise SignInRequired('Continue with ChatGPT to enable summaries')
            if saved.get('expires_at',0) <= time.time()+90:
                response = self.http.post(TOKEN_URL, data={'grant_type':'refresh_token','client_id':saved['client_id'],
                                          'refresh_token':saved['refresh_token'],'resource':RESOURCE})
                if response.status_code != 200: raise SignInRequired('ChatGPT sign-in needs renewal')
                self._save(response.json(), saved)
                saved = self.state.read('session')
            return saved['access_token']

    def account(self):
        self.token()
        s = self.state.read('session')
        return hashlib.sha256((s['client_id']+'\0'+s['subject']).encode()).hexdigest()
