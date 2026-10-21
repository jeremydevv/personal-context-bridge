import json
import tempfile
import unittest
from pathlib import Path
from personal_context.enrichment import EnrichmentClient, EnrichmentError
from personal_context.subscription_auth import AuthSession, PrivateState

SCHEMA={'type':'object','properties':{'title':{'type':'string'}},'required':['title'],'additionalProperties':False}

class AuthTests(unittest.TestCase):
    def test_private_encrypted_atomic_and_pending_state(self):
        with tempfile.TemporaryDirectory() as d:
            state=PrivateState(Path(d), b'x'*32)
            state.write('example',{'secret':'fictional sensitive text'})
            self.assertEqual(state.read('example')['secret'],'fictional sensitive text')
            self.assertNotIn(b'fictional', (Path(d)/'example.enc').read_bytes())
            self.assertEqual((Path(d)/'example.enc').stat().st_mode & 0o777,0o600)
            a=AuthSession(state)
            first=a.begin()
            self.assertIn('code_challenge_method=S256',first)
            self.assertIn('dynamic_agent_client',first)
            with self.assertRaises(ValueError):a.complete({'state':'wrong','code':'fake'})
            self.assertFalse(a.status()['authenticated'])
            host=state.read('host')['id']
            self.assertEqual(AuthSession(state).state.read('host')['id'],host)

class EnrichmentTests(unittest.TestCase):
    def client(self, root, events):
        def stream(body):
            self.calls+=1
            return iter(events)
        state=PrivateState(Path(root),b'y'*32)
        return EnrichmentClient(state=state,model='fictional-model',account='fixture',stream=stream)
    def test_cache_and_source_invalidation(self):
        with tempfile.TemporaryDirectory() as d:
            self.calls=0
            c=self.client(d,[{'type':'response.completed','response':{'output':[{'type':'message','content':[{'type':'output_text','text':'{"title":"Library"}'}]}]}}])
            args=dict(task='place',instructions='Use evidence',input_data={'label':'Library'},output_schema=SCHEMA,source_digest='one',source_version='1',prompt_version='1')
            self.assertEqual(c.enrich_json(**args)['value']['title'],'Library')
            self.assertTrue(c.enrich_json(**args)['cache_hit'])
            args['source_digest']='two';c.enrich_json(**args)
            self.assertEqual(self.calls,2)
    def test_incomplete_failure_and_invalid_schema_never_cache(self):
        for events in ([],[{'type':'response.failed'}],[{'type':'response.incomplete'}],[{'type':'response.completed','response':{'output':[]}}]):
            with self.subTest(events=events),tempfile.TemporaryDirectory() as d:
                self.calls=0;c=self.client(d,events)
                for _ in range(2):
                    with self.assertRaises(EnrichmentError):c.enrich_json('voice','summarize',{},SCHEMA,'x','1','1')
                self.assertEqual(self.calls,2)

class OAuthValidationTests(unittest.TestCase):
    def test_signed_identity_and_scope_validation(self):
        import jwt,time
        from cryptography.hazmat.primitives.asymmetric import rsa
        import httpx
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()));jwk['kid']='fixture'
        def handler(request):
            return httpx.Response(200,json={'keys':[jwk]})
        with tempfile.TemporaryDirectory() as d:
            auth=AuthSession(PrivateState(Path(d),b'w'*32),httpx.Client(transport=httpx.MockTransport(handler)))
            claims={'iss':'https://auth.openai.com','aud':'fictional-client','sub':'fixture','iat':time.time(),'exp':time.time()+100,'nonce':'expected'}
            token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'fixture'})
            self.assertEqual(auth.validate_identity(token,'fictional-client','expected')['sub'],'fixture')
            with self.assertRaises(ValueError):auth.validate_identity(token,'fictional-client','wrong')
            with self.assertRaises(jwt.InvalidAudienceError):auth.validate_identity(token,'wrong','expected')
            with self.assertRaises(Exception):auth._save({'access_token':'fictional','scope':'openid'}, {})

    def test_rotation_saves_new_refresh_atomically(self):
        import time,httpx
        with tempfile.TemporaryDirectory() as d:
            state=PrivateState(Path(d),b'v'*32)
            state.write('session',{'client_id':'fixture','subject':'fixture','access_token':'old','refresh_token':'old-refresh','expires_at':0,'scopes':['chatgpt.tokens.use.direct']})
            seen=[]
            def handler(request):
                seen.append(request.content)
                return httpx.Response(200,json={'access_token':'new','refresh_token':'new-refresh','expires_in':3600,'scope':'chatgpt.tokens.use.direct'})
            auth=AuthSession(state,httpx.Client(transport=httpx.MockTransport(handler)))
            self.assertEqual(auth.token(),'new');self.assertEqual(auth.token(),'new')
            self.assertEqual(len(seen),1)
            self.assertEqual(state.read('session')['refresh_token'],'new-refresh')
