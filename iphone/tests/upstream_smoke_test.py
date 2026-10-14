#!/usr/bin/env python3
"""Posts every fixture in docs/protocol/fixtures to a receiver and checks the responses.

    smoke_test.py                                   spawn receiver.py on a free port with a temp DB
    smoke_test.py --url http://host:8080 --token T   test a running receiver (any implementation)

Fixtures are applied in file-name order to what must be an empty store: the
expected counts in each .expected.json assume that order (fixture 05 deletes a
sample fixture 01 stored). Each fixture is then replayed at once, which must be
a 2xx no-op. Exit status 0 when every check passes. Standard library only.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
USER = "5ea4d000-0000-4000-8000-000000000001"
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def request(url, token, method="GET", body=None, headers=None):
    """Returns (status, parsed JSON body or None). Never raises for HTTP errors."""
    h = {"Authorization": f"Bearer {token}", "X-Puls-Protocol": "1", "X-User-ID": USER}
    h.update(headers or {})
    if token is None:
        del h["Authorization"]
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw) if raw.strip() else None
    except ValueError:
        return status, None


def post_batch(base, token, ndjson_text, batch_id=None, headers=None):
    h = {"Content-Type": "application/x-ndjson", "Content-Encoding": "gzip"}
    if batch_id:
        h["X-Batch-ID"] = batch_id
    h.update(headers or {})
    return request(base + "/v1/batches", token, "POST", gzip.compress(ndjson_text.encode()), h)


def run(base, token):
    base = base.rstrip("/")
    status, body = request(base + "/healthz", None)
    check(status == 200, f"GET /healthz -> {status}")

    status, body = request(base + "/v1/capabilities", token)
    if status == 404:
        print("info GET /v1/capabilities not implemented (allowed); the app will probe with an empty batch")
    else:
        check(status == 200 and isinstance(body, dict) and 1 in body.get("protocolVersions", []),
              f"GET /v1/capabilities -> {status} {body}")
        check(status == 200 and "batches" in (body or {}).get("features", []), "capabilities advertise batches")
        status, _ = request(base + "/v1/capabilities", "not-the-token")
        check(status == 401, f"GET /v1/capabilities with a wrong token -> {status} (want 401)")

    for name in sorted(f for f in os.listdir(FIXTURES) if f.endswith(".ndjson")):
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
            text = f.read()
        with open(os.path.join(FIXTURES, name[:-len(".ndjson")] + ".expected.json"), encoding="utf-8") as f:
            expected = json.load(f)
        batch_id = json.loads(text.split("\n", 1)[0])["batchID"]
        status, body = post_batch(base, token, text, batch_id)
        check(status == expected["status"], f"{name}: status {status} (want {expected['status']})")
        if body is None:
            print(f"info {name}: no JSON counts in the response (allowed); counts not compared")
        else:
            got = {k: body.get(k) for k in expected["response"]}
            check(got == expected["response"], f"{name}: counts {got} (want {expected['response']})")
        status, body = post_batch(base, token, text, batch_id)
        check(200 <= status < 300, f"{name}: replay -> {status} (want 2xx)")
        if body is not None:
            check(body.get("accepted") == 0, f"{name}: replay accepted {body.get('accepted')} (want 0)")

    probe = ('{"schemaVersion":1,"clientVersion":"smoke-test","batchID":"%s","deviceID":"smoke","type":"HKQuantityTypeIdentifierHeartRate",'
             '"reason":"manual","exportedAt":1718000000000,"sampleCount":%d,"deletionCount":0}\n')
    status, _ = post_batch(base, "not-the-token", probe % ("b0000000-0000-4000-8000-000000000001", 0))
    check(status == 401, f"POST with a wrong token -> {status} (want 401)")
    status, body = post_batch(base, token, probe % ("b0000000-0000-4000-8000-000000000002", 0), headers={"X-Puls-Protocol": "2"})
    check(status == 400 and isinstance(body, dict) and 1 in body.get("supportedVersions", []),
          f"POST with X-Puls-Protocol: 2 -> {status} {body} (want 400 + supportedVersions)")
    status, body = post_batch(base, token, probe.replace('"schemaVersion":1', '"schemaVersion":2') % ("b0000000-0000-4000-8000-000000000003", 0))
    check(status == 400 and isinstance(body, dict) and 1 in body.get("supportedVersions", []),
          f"POST with schemaVersion 2 -> {status} {body} (want 400 + supportedVersions)")
    status, _ = post_batch(base, token, "definitely not ndjson\n")
    check(status == 400, f"POST garbage -> {status} (want 400)")
    status, _ = post_batch(base, token, probe % ("b0000000-0000-4000-8000-000000000004", 1))
    check(status == 400, f"POST header declaring a sample that never comes -> {status} (want 400)")
    status, _ = post_batch(base, token, probe % ("b0000000-0000-4000-8000-000000000005", 1) + '{"mystery":{"uuid":"x"}}\n')
    check(status == 400, f"POST unknown line type -> {status} (want 400)")
    status, _ = post_batch(base, token, probe % ("b0000000-0000-4000-8000-000000000006", 0), headers={"X-User-ID": "not-a-uuid"})
    check(status == 400, f"POST with a malformed X-User-ID -> {status} (want 400)")
    status, _ = request(base + "/v1/batches", token, "POST", b"\x1f\x8bnot gzip",
                        {"Content-Type": "application/x-ndjson", "Content-Encoding": "gzip"})
    check(status == 400, f"POST invalid gzip -> {status} (want 400)")


def spawn():
    """Start receiver.py on a free loopback port with a throwaway database."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    tmp = tempfile.mkdtemp(prefix="puls-smoke-")
    token_file = os.path.join(tmp, "token")
    key_file = os.path.join(tmp, "key")
    with open(token_file, "w", encoding="utf-8") as f:
        f.write("smoke-test-token-long-enough-for-the-receiver")
    with open(key_file, "wb") as f:
        f.write(bytes(range(32)))
    env = dict(os.environ, PULS_TOKEN_FILE=token_file, PULS_KEY_FILE=key_file,
               PULS_DB=os.path.join(tmp, "puls.sqlite"), PULS_PORT=str(port))
    proc = subprocess.Popen([sys.executable, "-m", "iphone_context.health_receiver"], env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if request(base + "/healthz", None)[0] == 200:
                return proc, base, "smoke-test-token-long-enough-for-the-receiver"
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(0.1)
    proc.kill()
    sys.exit("receiver.py did not come up")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="base URL of a running receiver (default: spawn receiver.py)")
    ap.add_argument("--token", help="bearer token for --url (or PULS_TOKEN)")
    args = ap.parse_args()
    proc = None
    if args.url:
        base, token = args.url, args.token or os.environ.get("PULS_TOKEN")
        if not token:
            sys.exit("--token or PULS_TOKEN is required with --url")
    else:
        proc, base, token = spawn()
    try:
        run(base, token)
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=10)
    print(f"\n{len(failures)} failure(s)" if failures else "\nall checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
