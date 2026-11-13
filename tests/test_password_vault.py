import base64
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.personal_center import register_personal_center_routes


def test_vault_authentication_encrypted_storage_and_conflict(tmp_path, monkeypatch):
    keys = {}
    monkeypatch.setattr("backend.personal_center._vault_read_key", lambda: keys.get("key", ""))
    monkeypatch.setattr("backend.personal_center._vault_write_key", lambda value: keys.update(key=value))
    db = tmp_path / 'test.sqlite'

    @contextmanager
    def get_db():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    app = FastAPI()
    register_personal_center_routes(app, get_db, Path('frontend'))
    client = TestClient(app)
    assert client.post('/api/personal-center/security/set-password', json={'password': 'testpass'}).status_code == 200
    assert client.get('/api/personal-center/password-vault').status_code == 401
    assert client.post('/api/personal-center/password-vault/key').status_code == 401
    token = client.post('/api/personal-center/verify/password', json={'password': 'testpass'}).json()['token']
    headers = {'x-pc-token': token}
    url = '/api/personal-center/password-vault'
    key = client.post(url + '/key', headers=headers).json()['key']
    assert key and client.post(url + '/key', headers=headers).json()['key'] == key
    assert client.get(url, headers=headers).json() == {'payload': None, 'revision': 0}
    enc = lambda b: base64.b64encode(b).decode()
    payload = {'version': 1, 'salt': enc(b'a'*16), 'iv': enc(b'b'*12), 'ciphertext': enc(b'c'*40)}
    assert client.put(url, headers=headers, json={'revision': 0, 'payload': payload}).json() == {'revision': 1}
    assert client.get(url, headers=headers).json() == {'payload': payload, 'revision': 1}
    assert client.put(url, headers=headers, json={'revision': 0, 'payload': payload}).status_code == 409
    assert client.put(url, headers=headers, json={'revision': 1, 'payload': {**payload, 'ciphertext': 'bad'}}).status_code == 400
    assert client.get(url, headers=headers).json()['payload'] == payload

    keys.clear()
    assert client.post(url + '/key', headers=headers).status_code == 503
    assert keys == {}
