"""Exercise the real OAuth/client/adapters with a wholly fictional HTTP provider.

This checks transport and cross-feature reuse; it never represents real consent.
"""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from personal_context.enrichment import EnrichmentClient
from personal_context.location_dictionary import LocationDictionary
from personal_context.subscription_auth import AuthSession, PrivateState, SCOPES
from personal_context.voice_memos_worker import SharedSummarizer


class SharedSubscriptionFlowTests(unittest.TestCase):
    def test_authorization_model_discovery_both_consumers_and_restart_cache(self):
        signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
        public_key['kid'] = 'fictional-signing-key'
        requests = []
        original_client = httpx.Client
        with tempfile.TemporaryDirectory() as directory:
            state = PrivateState(Path(directory), b'k' * 32)

            def provider(request):
                requests.append(request)
                if request.url.path.endswith('/oauth/token'):
                    form = parse_qs(request.content.decode())
                    self.assertEqual(form['client_id'], ['fictional-issued-client'])
                    if form['grant_type'] == ['authorization_code']:
                        self.assertEqual(form['code_verifier'], [pending['verifier']])
                        self.assertEqual(form['redirect_uri'], [pending['redirect_uri']])
                    claims = {'iss': 'https://auth.openai.com', 'aud': 'fictional-issued-client',
                              'sub': 'fictional-user', 'iat': time.time(),
                              'exp': time.time() + 3600, 'nonce': pending['nonce']}
                    identity = jwt.encode(claims, signing_key, algorithm='RS256',
                                          headers={'kid': 'fictional-signing-key'})
                    return httpx.Response(200, json={'access_token': 'fictional-access',
                        'refresh_token': 'fictional-refresh', 'id_token': identity,
                        'token_type': 'Bearer', 'expires_in': 3600, 'scope': SCOPES})
                if request.url.path.endswith('/jwks.json'):
                    return httpx.Response(200, json={'keys': [public_key]})
                self.assertEqual(request.headers['authorization'], 'Bearer fictional-access')
                if request.url.path == '/v1/models':
                    return httpx.Response(200, json={'models': [
                        {'slug': 'fictional-model', 'display_name': 'Fixture', 'visibility': 'list'}]})
                self.assertEqual(request.url.path, '/v1/responses')
                body = json.loads(request.content)
                self.assertFalse(body['store'])
                self.assertTrue(body['stream'])
                self.assertEqual(body['model'], 'fictional-model')
                fields = body['text']['format']['schema']['properties']
                value = {name: ('unknown' if name == 'visit_reason' else 'Fictional evidence')
                         for name in fields}
                event = {'type': 'response.completed', 'response': {'status': 'completed',
                    'output': [{'type': 'message', 'content': [
                        {'type': 'output_text', 'text': json.dumps(value)}]}]}}
                return httpx.Response(200, text='event: response.completed\ndata: ' +
                                      json.dumps(event) + '\n\ndata: [DONE]\n\n',
                                      headers={'content-type': 'text/event-stream'})

            transport = httpx.MockTransport(provider)
            auth = AuthSession(state, original_client(transport=transport))
            url = auth.begin()
            query = parse_qs(urlsplit(url).query)
            pending = state.read('pending')
            self.assertEqual(query['client_id'], ['dynamic_agent_client'])
            completed = auth.complete({'state': pending['state'], 'code': 'fictional-code',
                                       'client_id': 'fictional-issued-client'})
            self.assertTrue(completed['authenticated'])
            self.assertTrue(completed['plan_usage_enabled'])
            with self.assertRaises(ValueError):
                auth.complete({'state': pending['state'], 'code': 'fictional-code',
                               'client_id': 'fictional-issued-client'})

            def http_client(*args, **kwargs):
                return original_client(transport=transport, *args, **kwargs)

            with patch('personal_context.enrichment.httpx.Client', side_effect=http_client):
                shared = EnrichmentClient(state=state, auth=auth)
                voice = SharedSummarizer(shared)
                transcript = {'task': 'voice_memo_part', 'text': 'Entirely fictional source text.'}
                self.assertEqual(voice(transcript)['summary'], 'Fictional evidence')
                dictionary = LocationDictionary(state)
                points = [{'id': 'fictional-point', 'timestamp': 1000,
                           'latitude': 40., 'longitude': -75., 'accuracy_m': 5}]
                dictionary.update(points, client=shared)
                place = dictionary.search()['places'][0]
                self.assertTrue(place['generated_is_current'])
                self.assertEqual(place['summary'], 'Fictional evidence')
                self.assertEqual(place['generated_visit_reason'], 'unknown')
                self.assertEqual(len([r for r in requests if r.url.path == '/v1/responses']), 2)

                # Restart both consumers over the same protected session and cache.
                restarted = EnrichmentClient(state=PrivateState(Path(directory), b'k' * 32),
                    auth=AuthSession(state, original_client(transport=transport)))
                self.assertEqual(SharedSummarizer(restarted)(transcript)['summary'], 'Fictional evidence')
                dictionary.update(points, client=restarted)
                self.assertEqual(len([r for r in requests if r.url.path == '/v1/responses']), 2)
                self.assertEqual(len([r for r in requests if r.url.path.endswith('/oauth/token')]), 1)
