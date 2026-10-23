"""Opt-in Windows installation metrics, bounded to one attempt per rolling six hours."""
from __future__ import annotations
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path
import requests

INTERVAL = 21_600
ENDPOINT = 'https://stella-admin.pages.dev/v1/events'


def windows_version():
    version = sys.getwindowsversion()
    return f'Windows {version.major}.{version.minor}.{version.build}'


def post_event(payload):
    # A fresh, credential-free session; no cookies, redirects, disk queue or netrc.
    with requests.Session() as session:
        session.trust_env = False
        response = session.post(ENDPOINT, json=payload, timeout=(5, 10), allow_redirects=False,
                                headers={'User-Agent': 'Stella-Windows-Metrics/1'})
        return response.status_code == 204


class Statistics:
    def __init__(self, root, build, lock, write, *, clock=time.time, post=post_event, version=windows_version):
        self.folder = Path(root) / 'userdata'
        self.path = self.folder / 'anonymous-statistics.json'
        self.lock = lock
        self.write = write
        self.clock = clock
        self.post = post
        self.version = version
        self.build = str(build)
        if not self.build.isdigit() or not 1 <= len(self.build) <= 18:
            raise ValueError('invalid metrics build')

    def read(self):
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 1024:
                return {}
            data = json.loads(self.path.read_bytes())
            if not isinstance(data, dict) or type(data.get('allowed')) is not bool:
                return {}
            identifier = data.get('install_id', '')
            if not isinstance(identifier, str):
                return {}
            if identifier and (str(uuid.UUID(identifier)) != identifier or uuid.UUID(identifier).version != 4):
                return {}
            stamp = data.get('last_attempt')
            if stamp is not None and (type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0):
                return {}
            return {'allowed': data['allowed'], 'install_id': identifier, 'last_attempt': stamp}
        except (OSError, ValueError, TypeError):
            return {}

    def save(self, data):
        self.write(self.path, data)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def status(self):
        return {'allowed': self.read().get('allowed'), 'interval_seconds': INTERVAL}

    def consent(self, allowed):
        if type(allowed) is not bool:
            raise ValueError('invalid consent')
        self.folder.mkdir(parents=True, exist_ok=True)
        with self.lock(self.folder / 'anonymous-statistics.lock'):
            data = self.read()
            data['allowed'] = allowed
            data.setdefault('last_attempt', None)
            data.setdefault('install_id', '')
            if allowed and not data['install_id']:
                data['install_id'] = str(uuid.uuid4())
            self.save(data)
        return self.status()

    def run_due(self):
        """Reserve the attempt on disk before networking; restarts/retries share this gate."""
        if self.read().get('allowed') is not True:
            return INTERVAL
        try:
            with self.lock(self.folder / 'anonymous-statistics.lock'):
                data = self.read()
                if data.get('allowed') is not True:
                    return INTERVAL
                now = self.clock()
                stamp = data.get('last_attempt')
                remaining = INTERVAL - (now - stamp) if stamp is not None else 0
                if remaining > 0:
                    return max(1, remaining)
                if not data.get('install_id'):
                    return INTERVAL
                payload = {'install_id': data['install_id'], 'version': self.build, 'os': self.version()}
                data['last_attempt'] = now
                self.save(data)
            self.post(payload)
        except (OSError, RuntimeError, ValueError, requests.RequestException):
            # No immediate retry, and a networking failure cannot interrupt Stella.
            return INTERVAL
        return INTERVAL
