"""Batch hydration for the existing offline case-detail wire format."""
from __future__ import annotations

import json
import re
from collections import defaultdict


def build_details(conn, case_ids, audit_names):
    """Use one snapshot and bounded IN batches, never one connection per case."""
    def select(table, key, ids, order='id'):
        result = []
        values = list(dict.fromkeys(ids))
        for offset in range(0, len(values), 800):
            part = values[offset:offset + 800]
            marks = ','.join('?' for _ in part)
            result.extend(dict(row) for row in conn.execute(
                f'SELECT * FROM {table} WHERE {key} IN ({marks}) ORDER BY {order}', part))
        return result

    cases = {r['id']: r for r in select('case_manager_cases', 'id', case_ids)}
    children = select('case_manager_cases', 'parent_series_id', case_ids, 'series_order,id')
    cases.update({r['id']: r for r in children if r.get('case_kind') == 'series_child'})
    ids = list(cases)
    specifications = {
        'parties': ('parties', 'sort_order,id'), 'case_numbers': ('case_numbers', 'sort_order,id'),
        'todos': ('todos', 'datetime(remind_at) DESC,id DESC'),
        'hearings': ('hearings', 'datetime(hearing_at) DESC,id DESC'),
        'preservations': ('preservations', 'date(deadline_at) DESC,id DESC'),
        'appeals': ('appeals', 'date(deadline_at) DESC,id DESC'),
        'claims': ('claims', 'sort_order,id'),
        'milestones': ('milestones', 'datetime(happened_at),sort_order,id'),
        'audit_logs': ('audit_logs', 'datetime(created_at) DESC,id DESC'),
    }
    for field, (suffix, order) in specifications.items():
        groups = defaultdict(list)
        for row in select('case_manager_' + suffix, 'case_id', ids, order):
            groups[row['case_id']].append(row)
        for case in cases.values():
            case[field] = groups[case['id']][:300] if field == 'audit_logs' else groups[case['id']]
    client_ids = {p['client_id'] for c in cases.values() for p in c['parties']
                  if p.get('party_group') == 'client' and p.get('client_id')}
    clients = {r['id']: r for r in select('case_manager_clients', 'id', client_ids, 'name')}
    profiles = {r['series_case_id']: r for r in select('case_manager_series_profiles', 'series_case_id', ids, 'series_case_id')}
    court = court_rows(conn)
    for case in cases.values():
        case['client_profiles'] = sorted(
            [dict(clients[i]) for i in {p.get('client_id') for p in case['parties']
              if p.get('party_group') == 'client'} if i in clients], key=lambda r: r.get('name') or '')
        for client in case['client_profiles']:
            try:
                contacts = json.loads(client.get('contacts_json') or '[]')
            except (TypeError, ValueError):
                contacts = []
            client['contacts'] = [{'name': str(r.get('name') or '').strip(),
                                   'phone': str(r.get('phone') or '').strip()}
                                  for r in contacts if isinstance(r, dict)]
        codes = {p['id']: p.get('identity_code') or '' for p in case['client_profiles']}
        for party in case['parties']:
            if party.get('party_group') == 'client' and not str(party.get('credit_code') or '').strip():
                party['credit_code'] = codes.get(party.get('client_id'), '')
        for log in case['audit_logs']:
            try:
                log['changes'] = json.loads(log.pop('changes_json', '[]') or '[]')
            except (TypeError, ValueError):
                log['changes'] = []
            log['entity_name'] = audit_names.get(log.get('entity_type'), log.get('entity_type') or '记录')
        if case.get('case_kind') == 'series':
            case['profile'] = profiles.get(case['id'], {})
            case['common_claims'] = list(case['claims'])
            case['series_children'] = [cases[c['id']] for c in children
                                       if c['id'] in cases and c.get('parent_series_id') == case['id']
                                       and c.get('case_kind') == 'series_child']
        case['court_online'] = court_links(court, case)
    return cases


COURT_FIELDS = {
    'cases': 'id,case_number,case_name,cause,business_type,court_name,judge,department,stage,status,parties,filing_date,judgment_date,update_date',
    'layy': 'id,court_name,case_type,parties,case_name,status,cause,review_comment,filed_date,update_date,applicant,apply_time,submit_time,judge,case_number,material_count,material_time,withdraw_time,category',
    'records': 'id,kind,title,content,published_at,unread,delivery_status,case_number,case_name,court_name,case_space_url,linked_case_id,updated_at',
    'hearings': 'id,case_number,case_name,court_name,hearing_type,hearing_at,location,judge,status,linked_case_id,updated_at',
}


def court_rows(conn):
    try:
        from .court_online_service import _active_account_id
        account = _active_account_id()
    except Exception:
        account = ''
    result = {}
    for kind, fields in COURT_FIELDS.items():
        result[kind] = []
        if not account:
            continue
        order = {'cases': 'datetime(update_date)', 'layy': 'datetime(update_date)',
                 'records': "datetime(COALESCE(NULLIF(published_at,''),updated_at))",
                 'hearings': 'datetime(hearing_at)'}[kind]
        if 'linked_case_id' not in fields.split(','):
            fields += ',linked_case_id'
        try:
            result[kind] = [dict(r) for r in conn.execute(
                f'SELECT {fields} FROM case_manager_court_online_{kind} WHERE account_id=? ORDER BY {order} DESC,id DESC', (account,))]
        except Exception:
            pass  # Optional integrations are absent in old/anonymous databases.
    return result


def court_links(rows, case):
    compact = {re.sub(r'[\s（）()《》〈〉·.]', '', str(r.get('case_no') or ''))
               for r in case.get('case_numbers', []) if re.search(r'\d', str(r.get('case_no') or ''))}
    title = str(case.get('title') or '').strip()
    result = {}
    for kind, candidates in rows.items():
        linked = [r for r in candidates if r.get('linked_case_id') == case['id']]
        extra = [r for r in candidates if not r.get('linked_case_id') and (
            (kind != 'layy' and re.sub(r'[\s（）()]', '', str(r.get('case_number') or '')) in compact)
            or (kind == 'layy' and len(title) >= 6 and title.casefold() in str(r.get('case_name') or '').casefold()))]
        limit = {'records': 30, 'hearings': 20}.get(kind)
        matches = linked[:limit] + extra[:limit] if limit else linked + extra
        if kind in {'records', 'hearings'}:
            date = 'published_at' if kind == 'records' else 'hearing_at'
            matches.sort(key=lambda r: str(r.get(date) or r.get('updated_at') or ''), reverse=True)
            matches = matches[:limit]
        fields = COURT_FIELDS[kind].split(',')
        result[kind] = [{k: r.get(k) for k in fields} for r in matches]
    return result
