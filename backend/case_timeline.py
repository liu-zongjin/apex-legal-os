"""Grounded case event chronology. Dates are parsed, never completed by inference."""
import calendar
import datetime as dt
import hashlib
import json
import re
from collections import defaultdict
from fastapi import HTTPException
from .citation_locations import display_locator

MAX_EVENTS=300
REVIEW={'pending':'待复核','confirmed':'已确认','amended':'人工修改','excluded':'不纳入时间轴'}


def date_bounds(value):
    """Bounds only support sorting; displayed text retains source precision."""
    value=value.strip()
    def one(text):
        patterns=[(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?', 'day'),
                  (r'(\d{4})年(\d{1,2})月','month'),(r'(\d{4})年?','year')]
        for pattern,precision in patterns:
            match=re.fullmatch(pattern,text.strip())
            if not match:continue
            parts=[int(p) for p in match.groups()]
            try:
                if precision=='day':start=end=dt.date(*parts)
                elif precision=='month':
                    year,month=parts;start=dt.date(year,month,1);end=dt.date(year,month,calendar.monthrange(year,month)[1])
                else:start=dt.date(parts[0],1,1);end=dt.date(parts[0],12,31)
                return start.isoformat(),end.isoformat(),precision
            except ValueError:return None
        return None
    result=one(value)
    if result:return {'sort_start':result[0],'sort_end':result[1],'date_precision':result[2],'date_warning':''}
    ranges=re.split(r'\s*(?:至|到|～|~|—)\s*',value)
    if len(ranges)==2:
        first,last=one(ranges[0]),one(ranges[1])
        if first and last and first[0]<=last[1]:return {'sort_start':first[0],'sort_end':last[1],'date_precision':'range','date_warning':''}
    return {'sort_start':'','sort_end':'','date_precision':'unknown','date_warning':'日期不确定，保留原始表述；不补写具体日期。'}


def grounded_event(proposal,sources):
    from .case_workflows import plain
    if not isinstance(proposal,dict):raise HTTPException(422,'事件格式无效')
    source=next((row for row in sources if row['id']==str(proposal.get('source_id',''))),None)
    quote=plain(proposal.get('quote',''),1200)
    if not source or len(quote)<4 or quote not in source['text']:
        return None  # Never publish an event without a literal, case-scoped citation.
    description=plain(proposal.get('description',''),1200)
    if not description:raise HTTPException(422,'AI未填写事件内容')
    date_text=plain(proposal.get('date_text',''),100)
    warning=''
    if date_text and date_text not in quote:
        date_text='';warning='AI日期未出现在引句中，未采用；请回看原件。'
    actors=plain(proposal.get('actors',''),300)
    if actors and actors not in source['text']:
        actors=''
    ref={key:source[key] for key in ('id','path','sha256','locator','chunk_index')}
    ref['quote']=quote
    identifier=hashlib.sha256(json.dumps([source['path'],source['locator'],quote,date_text,description,actors,proposal.get('topic','')],ensure_ascii=False).encode()).hexdigest()[:24]
    return {'id':identifier,'description':description,'actors':actors,'date_text':date_text,
            'topic':plain(proposal.get('topic',''),200),**date_bounds(date_text),
            'date_warning':warning or date_bounds(date_text)['date_warning'],
            'evidence':[ref],'review_status':'pending','review_note':'','original':{'date_text':date_text,'description':description,'actors':actors}}


def ordered(events):
    return sorted(events,key=lambda row:(not bool(row['sort_start']),row['sort_start'],row['sort_end'],row['id']))


def issues(events):
    groups=defaultdict(list)
    for row in events:
        if row['review_status']=='excluded':continue
        key=re.sub(r'\W+','',row['topic']).lower()
        if key:groups[(key,row['actors'])].append(row)
    result=[]
    for rows in groups.values():
        if len(rows)<2:continue
        bounds={(row['sort_start'],row['sort_end']) for row in rows if row['sort_start']}
        result.append({'type':'date_difference' if len(bounds)>1 else 'possible_duplicate',
            'label':'同一事项候选存在日期差异，需核对是否实际为不同事件' if len(bounds)>1 else '可能重复的事件，保留各份材料的记录',
            'event_ids':[row['id'] for row in rows]})
    return result


def review_events(events,updates):
    from .case_workflows import plain
    if not isinstance(updates,list) or len(updates)!=len(events):raise HTTPException(422,'请保存全部事件，不纳入的事件请标记排除')
    by_id={row.get('id'):row for row in updates if isinstance(row,dict) and isinstance(row.get('id'),str)}
    if len(by_id)!=len(updates) or set(by_id)!={row['id'] for row in events}:raise HTTPException(422,'事件编号不一致')
    output=[]
    for original in events:
        update=by_id[original['id']]
        status=update.get('status')
        if not isinstance(status,str) or status not in REVIEW:raise HTTPException(422,'事件复核状态无效')
        description=plain(update.get('description',original['description']),1200)
        date_text=plain(update.get('date_text',original['date_text']),100)
        actors=plain(update.get('actors',original['actors']),300)
        note=plain(update.get('note',''),2000)
        changed=any(value!=original['original'][key] for key,value in [('description',description),('date_text',date_text),('actors',actors)])
        if not description or ((changed or status in {'amended','excluded'}) and not note):raise HTTPException(422,'修改或排除事件时请填写复核意见')
        if changed and status not in {'amended','excluded'}:raise HTTPException(422,'修改了事件内容，请标记人工修改并填写意见')
        row={**original,**date_bounds(date_text),'date_text':date_text,'description':description,'actors':actors,'review_status':status,'review_note':note}
        if date_text and not any(date_text in ref['quote'] for ref in row['evidence']):row['date_warning']='人工日期与原始引句不同，请结合复核意见核对。'
        output.append(row)
    return ordered(output)


def artifacts(job,folder):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment
    from .case_timeline_document import write_document
    from .timeline_presentation import presentation,svg,pdf,confirmed_position
    events=ordered(job['timeline_events']);job['timeline_issues']=issues(events)
    rows,refs,settings=presentation(events,job.get('export_options'));job['export_options']=settings
    wb=Workbook();ws=wb.active;ws.title='事实经过';ws.append(['序号','日期','主体','事实经过']+(['尾注'] if settings['include_evidence'] else []))
    lines=['# 案件事实时间轴','','日期保留原记录精度，事件间距不表示时长。','']
    for index,row in enumerate(rows,1):
        markers='、'.join(str(n) for n in row['note_numbers'])
        ws.append([index,row['date_text'] or '日期不明',row['actors'],row['description']]+([markers] if settings['include_evidence'] else []))
        lines += [f'## {index}. {row["date_text"] or "日期不明"}',row['description']+''.join(f'[^{n}]' for n in row['note_numbers'])]
        if row['actors']:lines.append('主体：'+row['actors'])
    if refs:
        notes=wb.create_sheet('原文依据');notes.append(['尾注编号','来源文件','已核实位置','原文引句'])
        for number,ref in enumerate(refs,1):
            notes.append([number,ref['path'],confirmed_position(ref),ref['quote']])
            lines.append(f'[^{number}]: '+ref['path']+(' · '+confirmed_position(ref) if confirmed_position(ref) else '')+'\n    '+ref['quote'].replace('\n','\n    '))
    for sheet in wb:
        sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width=42 if column[0].column>1 else 10
            for cell in column:
                if isinstance(cell.value,str):cell.data_type='s'
                cell.alignment=Alignment(wrap_text=True,vertical='top')
    wb.save(folder/'事实经过表.xlsx')
    write_document(events,folder/'事实经过表.docx',REVIEW,settings)
    (folder/'事实经过.md').write_text('\n\n'.join(lines),encoding='utf-8')
    (folder/'时间轴核验底稿.json').write_text(json.dumps({key:job.get(key) for key in ('case_id','revision','sources','timeline_events','timeline_issues','timeline_coverage','claims','results','export_options')},ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'事实时间轴.svg').write_text(svg(events,settings),encoding='utf-8')
    pdf(events,settings,folder/'事实时间轴.pdf')
