"""Private business defaults live in the installation's existing SQLite store."""
import json
import sqlite3

KEY = 'stella.business-profile.v1'
FIRM_FIELDS = ('name', 'address', 'credit_code', 'bank', 'account')


def read_business_profile(conn):
    try:
        row = conn.execute('SELECT value_json FROM app_preferences WHERE preference_key=?', (KEY,)).fetchone()
    except sqlite3.OperationalError:
        return {}
    value = json.loads(row[0]) if row else {}
    return value if isinstance(value, dict) else {}


def firm_defaults(conn):
    value = read_business_profile(conn).get('firm') or {}
    return {key: str(value.get(key) or '') for key in FIRM_FIELDS}


def chapter_approver(get_db):
    with get_db() as conn:
        return str(read_business_profile(conn).get('chapter_approver') or '').strip()
