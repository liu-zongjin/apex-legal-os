"""Default-on installation metrics with a persistent opt-out and six-hour sampling."""
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
RETRY_INTERVAL = 300
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
            delay = data.get('retry_delay', INTERVAL)
            if type(delay) not in (int, float) or not RETRY_INTERVAL <= delay <= INTERVAL:
                return {}
            return {'allowed': data['allowed'], 'install_id': identifier, 'last_attempt': stamp, 'retry_delay': delay}
        except (OSError, ValueError, TypeError):
            return {}

    def save(self, data):
        self.write(self.path, data)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def initialize(self):
        # Only a missing profile gets defaults. Preserve explicit opt-out and
        # fail closed on corrupt files or symlinks rather than replacing identity.
        if self.path.exists() or self.path.is_symlink():
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        for attempt in range(10):
            try:
                with self.lock(self.folder / 'anonymous-statistics.lock'):
                    if not self.path.exists() and not self.path.is_symlink():
                        self.save({'allowed': True, 'install_id': str(uuid.uuid4()),
                                   'last_attempt': None, 'retry_delay': INTERVAL})
                return
            except (OSError, RuntimeError):
                if self.path.exists() or self.path.is_symlink():
                    return
                if attempt == 9:
                    raise
                time.sleep(0.02)

    def status(self):
        self.initialize()
        return {'allowed': self.read().get('allowed', False), 'interval_seconds': INTERVAL}

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
        try:
            self.initialize()
            if self.read().get('allowed') is not True:
                return INTERVAL
            with self.lock(self.folder / 'anonymous-statistics.lock'):
                data = self.read()
                if data.get('allowed') is not True:
                    return INTERVAL
                now = self.clock()
                stamp = data.get('last_attempt')
                remaining = data.get('retry_delay', INTERVAL) - (now - stamp) if stamp is not None else 0
                if remaining > 0:
                    return max(1, remaining)
                if not data.get('install_id'):
                    return INTERVAL
                payload = {'install_id': data['install_id'], 'version': self.build, 'os': self.version()}
                data['last_attempt'] = now
                previous_delay = data.get('retry_delay', INTERVAL)
                data['retry_delay'] = RETRY_INTERVAL if previous_delay == INTERVAL else min(3600, previous_delay * 2)
                self.save(data)
            succeeded = self.post(payload) is not False
            if succeeded:
                with self.lock(self.folder / 'anonymous-statistics.lock'):
                    current = self.read()
                    if current.get('last_attempt') == now:
                        current['retry_delay'] = INTERVAL
                        self.save(current)
                return INTERVAL
            return data['retry_delay']
        except (OSError, RuntimeError, ValueError, requests.RequestException):
            # Bounded persistent backoff survives restarts; no busy retry loop.
            return self.read().get('retry_delay', INTERVAL)
        return INTERVAL
