"""Mailbox member labels, persisted independently of IMAP and summary eviction."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get('LEGAL_KB_RUNTIME_DIR', str(Path(__file__).resolve().parent.parent))) / 'data' / 'mail-team-labels'
_LOCK = threading.RLock()


def identity(mail):
    return {key: str(mail.get(key) or '') for key in ('date', 'from', 'subject')}


class LabelStore:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, account, folder):
        # Values must have been validated against the mailbox configuration.
        return self.root / f'{account}-{folder}.json'

    def read(self, account, folder):
        path = self.path(account, folder)
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise ValueError('invalid labels')
            return value
        except (OSError, ValueError) as exc:
            raise HTTPException(500, '邮件成员标注读取失败，请检查保存文件') from exc

    def update(self, account, folder, changes):
        with _LOCK:
            labels = self.read(account, folder)
            for uid, label in changes.items():
                if label is None:
                    labels.pop(uid, None)
                else:
                    labels[uid] = label
            self.root.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.root, prefix='.labels-')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                    json.dump(labels, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path(account, folder))
            finally:
                Path(temporary).unlink(missing_ok=True)
            return labels


class LabelRequest(BaseModel):
    account: str = 'netease_exmail'
    folder: str = 'inbox'
    uids: List[str] = Field(min_length=1, max_length=300)
    member_id: Optional[int] = None


def create_router(get_db, mail_service, root=ROOT):
    router = APIRouter(tags=['mail-team-labels'])
    store = LabelStore(root)

    def validate(account, folder):
        if account not in mail_service.MAILBOX_CONFIGS or folder not in ('inbox', 'sent', 'drafts'):
            raise HTTPException(400, '邮箱或文件夹无效')

    def members():
        with get_db() as conn:
            return [{'id': row[0], 'name': row[1]} for row in conn.execute(
                'SELECT id, name FROM suohan_lawyers ORDER BY id'
            )]

    @router.get('/api/qq-mail/team-labels')
    def snapshot(account: str = 'netease_exmail', folder: str = 'inbox'):
        validate(account, folder)
        with _LOCK:
            return {'members': members(), 'assignments': store.read(account, folder)}

    @router.put('/api/qq-mail/team-labels')
    def assign(payload: LabelRequest):
        validate(payload.account, payload.folder)
        uids = list(dict.fromkeys(payload.uids))
        if any(not uid.isascii() or not uid.isdigit() or len(uid) > 20 for uid in uids):
            raise HTTPException(400, '邮件标识无效')
        member = None
        if payload.member_id is not None:
            member = next((item for item in members() if item['id'] == payload.member_id), None)
            if member is None:
                raise HTTPException(400, '成员已变更，请重新选择')
        summaries = mail_service._load_summary_cache(payload.account, payload.folder)['mails']
        if member and any(uid not in summaries for uid in uids):
            raise HTTPException(409, '部分邮件摘要已过期，请刷新邮件后重新标注')
        changes = {uid: dict(member_id=member['id'], member_name=member['name'], identity=identity(summaries[uid]))
                   if member else None for uid in uids}
        try:
            labels = store.update(payload.account, payload.folder, changes)
        except OSError as exc:
            raise HTTPException(500, '标注保存失败，请重试') from exc
        return {'assignments': labels, 'updated_count': len(uids)}

    return router
