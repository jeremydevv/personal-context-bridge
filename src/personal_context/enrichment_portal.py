"""Private sign-in landing page plus loopback-only OAuth callback.

On a remote host forward the callback port over SSH before signing in. Browser
consent is always on auth.openai.com; this server never asks for a password.
"""
from __future__ import annotations
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit
from .subscription_auth import AuthSession


def run():
    auth=AuthSession()
    host=os.environ.get('PERSONAL_CONTEXT_AUTH_BIND','127.0.0.1')
    port=int(os.environ.get('PERSONAL_CONTEXT_AUTH_PORT','8793'))
    callback_port=int(os.environ.get('PERSONAL_CONTEXT_AUTH_CALLBACK_PORT','8794'))
    authority=f'{host}:{port}'
    csrf=secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # callbacks contain credentials
        def send(self,code,body,location=None):
            data=body.encode()
            self.send_response(code)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'none'; form-action 'self'; frame-ancestors 'none'")
            if location:self.send_header('Location',location)
            self.end_headers();self.wfile.write(data)
        def allowed(self):return self.headers.get('Host')==authority
        def do_GET(self):
            if not self.allowed():return self.send(403,'Host rejected')
            if self.path=='/healthz':return self.send(200,'Ready')
            if self.path!='/':return self.send(404,'Not found')
            status=auth.status()
            text='Signed in. Location and Voice Memos share this session.' if status['plan_usage_enabled'] else 'Sign in once to enable summaries for Location and Voice Memos.'
            self.send(200,'<!doctype html><html><meta name="viewport" content="width=device-width"><title>Personal Context sign-in</title>'
                '<h1>Personal Context</h1><p>'+html.escape(text)+'</p>'
                '<p>First run the Mac refresh prompt to open the secure callback tunnel. Then continue below. '
                'No API-key billing fallback is enabled. Your subscription usage limits apply.</p>'
                '<form method="post" action="/begin"><input type="hidden" name="csrf" value="'+csrf+'">'
                '<button>Continue with ChatGPT</button></form><p>After sign-in, processing resumes automatically.</p></html>')
        def do_POST(self):
            if not self.allowed() or self.path!='/begin':return self.send(403,'Request rejected')
            if self.headers.get('Origin')!=f'http://{authority}':return self.send(403,'Origin rejected')
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<4096:return self.send(400,'Invalid request')
                params=parse_qs(self.rfile.read(n).decode())
                if not secrets.compare_digest(params.get('csrf',[''])[0],csrf):return self.send(403,'Request rejected')
                url=auth.begin(callback_port)
                self.send(303,'Continue to ChatGPT',url)
            except (ValueError,UnicodeDecodeError):self.send(400,'Invalid request')

    class Callback(Handler):
        def do_POST(self):self.send(405,'Method not allowed')
        def do_GET(self):
            if self.headers.get('Host')!=f'127.0.0.1:{callback_port}':return self.send(403,'Host rejected')
            if urlsplit(self.path).path!='/auth/callback':return self.send(404,'Not found')
            try:
                raw=parse_qs(urlsplit(self.path).query)
                if any(len(v)!=1 for v in raw.values()):raise ValueError('ambiguous callback')
                result=auth.complete({k:v[0] for k,v in raw.items()})
                if not result['plan_usage_enabled']:raise ValueError('permission required')
                for unit in ('personal-context-location.service','personal-context-voice-enrich.service'):
                    subprocess.run(['systemctl','--user','start','--no-block',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                self.send(200,'<!doctype html><title>Connected</title><h1>Connected</h1><p>Location and Voice Memos now share your ChatGPT sign-in. Processing will resume automatically. You may close this tab.</p>')
            except Exception:
                self.send(400,'<!doctype html><title>Sign-in needs another attempt</title><h1>Please try again</h1><p>Sign-in could not be completed. Return to Personal Context and choose Continue with ChatGPT for a fresh attempt. No credentials were logged.</p>')

    callback=ThreadingHTTPServer(('127.0.0.1',callback_port),Callback)
    threading.Thread(target=callback.serve_forever,daemon=True).start()
    ThreadingHTTPServer((host,port),Handler).serve_forever()

if __name__=='__main__':run()
