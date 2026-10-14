"""Document-led evidence planning primitives, independent of provider/model SDKs."""
import re
from fastapi import HTTPException


def page_selection(value, count):
    """Physical source pages, in ascending order; never silently drop invalid pages."""
    if not isinstance(value, str) or len(value) > 2000:
        raise HTTPException(422, '选页格式无效')
    value = value.strip()
    if not value or value == '全部':
        return list(range(1, count + 1))
    selected = []
    for part in value.replace('，', ',').split(','):
        match = re.fullmatch(r'\s*(\d+)(?:\s*-\s*(\d+))?\s*', part)
        if not match:
            raise HTTPException(422, '选页请使用1-3,5这样的格式')
        start, end = int(match[1]), int(match[2] or match[1])
        if start < 1 or end < start or end > count:
            raise HTTPException(422, f'选页超出原件范围（共{count}页）')
        selected.extend(range(start, end + 1))
    if not selected or selected != sorted(set(selected)):
        raise HTTPException(422, '选页不能重复，且须按原件页码升序排列')
    return selected


def normalize_entries(entries, sources, claims, *, confirmed=False):
    from .case_workflows import plain
    if not isinstance(entries, list) or not 1 <= len(entries) <= 80:
        raise HTTPException(422, '证据清单需要1至80项')
    paths = {row['path'] for row in sources}
    ids = {row['id'] for row in claims}
    output = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise HTTPException(422, '证据条目格式无效')
        materials = entry.get('materials', [{'path':entry.get('path'), 'pages':''}])
        if not isinstance(materials, list) or not 1 <= len(materials) <= 40:
            raise HTTPException(422, '每项证据需包含1至40份材料')
        clean_materials = []
        for material in materials:
            if not isinstance(material, dict) or not isinstance(material.get('path'),str) or material.get('path') not in paths:
                raise HTTPException(422, '证据材料必须来自本次所选原件')
            clean_materials.append({'path':material['path'], 'pages':plain(material.get('pages',''),2000)})
        if len({row['path'] for row in clean_materials}) != len(clean_materials):
            raise HTTPException(422, '同一证据项不能重复加入同一材料；请用选页范围表达')
        claim_ids = entry.get('claim_ids', [])
        if not isinstance(claim_ids, list) or len(claim_ids)>80 or any(not isinstance(i,str) or i not in ids for i in claim_ids):
            raise HTTPException(422, '关联文书事项不属于本次编排依据')
        title, purpose = plain(entry.get('title',''),200), plain(entry.get('purpose',''),2000)
        if confirmed and (not title or not purpose):
            raise HTTPException(422, '请填写每项证据的名称和证明内容')
        output.append({'title':title, 'purpose':purpose, 'summary':plain(entry.get('summary',''),3000),
                       'origin':plain(entry.get('origin',''),600), 'group':plain(entry.get('group',''),200),
                       'claim_ids':list(dict.fromkeys(claim_ids)), 'materials':clean_materials})
    return output


def gaps(results, entries):
    output = []
    for row in results:
        if row.get('statement_type') in {'legal','request'}:
            continue
        linked = [entry for entry in entries if row['id'] in entry['claim_ids']]
        issue = ''
        if not linked:
            issue = '尚未关联编册证据'
        elif row['status']!='supported' or row.get('review_status') in {'rejected','amended'}:
            issue = '存在矛盾或未取得支持原文'
        else:
            included = False
            for ref in row['evidence']:
                match = re.search(r'第\s*(\d+)\s*页', ref['locator'])
                for entry in linked:
                    for material in entry['materials']:
                        if material['path']==ref['path'] and (not material['pages'].strip() or material['pages'].strip()=='全部' or (match and int(match[1]) in page_selection(material['pages'],1500))):
                            included=True
            if not included:
                issue='关联材料或选页未包含已核对引用，请重新确认证明依据'
        if issue:
            output.append({**row,'gap':issue})
    return output
