"""Grounded case event chronology. Dates are parsed, never completed by inference."""
import calendar
import datetime as dt
import hashlib
import html
import json
import re
import textwrap
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
    """Use identical reviewed text in tables and vector graphics; unknown dates get their own lane."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment
    from .case_timeline_document import write_document
    events=ordered(job['timeline_events'])
    job['timeline_issues']=issues(events)
    wb=Workbook();ws=wb.active;ws.title='事实经过'
    ws.append(['事件编号','日期原文／人工修订','日期精度','主体','事件内容','复核状态','复核意见','来源文件','页段','原文','日期提示'])
    note='日期保持原件精度；年月及期间的边界仅用于排序，不代表具体发生日。AI提取须复核，排除项不绘入时间轴。'
    lines=['# 案件事实经过时间轴','',note,'']
    graphic_rows=[]
    for index,row in enumerate(events,1):
        refs=row['evidence'];values=[row['id'],row['date_text'] or '日期不明',row['date_precision'],row['actors'],row['description'],REVIEW[row['review_status']],row['review_note'],'\n'.join(ref['path'] for ref in refs),'\n'.join(display_locator(ref['path'],ref['locator']) for ref in refs),'\n'.join(ref['quote'] for ref in refs),row['date_warning']]
        ws.append(values)
        lines += [f'## {index}. {row["date_text"] or "日期不明"}',REVIEW[row['review_status']],row['actors']+' · '+row['description'],row['date_warning'],row['review_note']]
        for ref in refs:
            text=ref['path']+' · '+display_locator(ref['path'],ref['locator'])+'\n'+ref['quote'];lines.append(text)
        if row['review_status']!='excluded':graphic_rows.append(row)
    ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
    for column in ws.columns:
        ws.column_dimensions[column[0].column_letter].width=40
        for cell in column:
            if isinstance(cell.value,str):cell.data_type='s'
            cell.alignment=Alignment(wrap_text=True,vertical='top')
    compare=wb.create_sheet('文书对照');compare.append(['文书事项','位置','初核结论','理由','引用原文'])
    for row in job.get('results',[]):compare.append([row['claim'],row.get('document_locator',''),row['status'],row['reason'],'\n'.join(ref['quote'] for ref in row['evidence'])])
    for cells in compare:
        for cell in cells:
            if isinstance(cell.value,str):cell.data_type='s'
    wb.save(folder/'事实经过表.xlsx')
    write_document(events,folder/'事实经过表.docx',REVIEW)
    (folder/'事实经过.md').write_text('\n\n'.join(lines),encoding='utf-8')
    (folder/'时间轴核验底稿.json').write_text(json.dumps({key:job.get(key) for key in ('case_id','revision','sources','timeline_events','timeline_issues','timeline_coverage','claims','results')},ensure_ascii=False,indent=2),encoding='utf-8')
    # Neutral numbered chronology: spacing never represents elapsed time.
    y=100;elements=[]
    for index,row in enumerate(graphic_rows,1):
        text=[row['actors']+' · '+row['description'],REVIEW[row['review_status']],row['date_warning']]
        if row['review_note']:text.append('复核意见：'+row['review_note'])
        text += [ref['path']+' · '+display_locator(ref['path'],ref['locator']) for ref in row['evidence']]
        wrapped=[piece for line in text if line for piece in textwrap.wrap(line,width=52,replace_whitespace=False,drop_whitespace=False)]
        dates=textwrap.wrap(row["date_text"] or "日期不明（不参与先后排序）",width=48)
        height=60+len(wrapped)*22+(len(dates)-1)*24
        elements += [f'<circle cx="40" cy="{y+20}" r="12" fill="#fff" stroke="#606770"/>',f'<text x="40" y="{y+24}" text-anchor="middle" font-size="11">{index}</text>']
        for offset,line in enumerate(dates):elements.append(f'<text x="70" y="{y+24+offset*24}" font-size="16" font-weight="bold">{html.escape(line)}</text>')
        for offset,line in enumerate(wrapped):elements.append(f'<text x="70" y="{y+54+(len(dates)-1)*24+offset*22}" font-size="13">{html.escape(line)}</text>')
        y+=height
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="920" height="{max(220,y+30)}" viewBox="0 0 920 {max(220,y+30)}"><rect width="100%" height="100%" fill="white"/><g font-family="SimSun,Songti SC,serif" fill="#202327"><text x="30" y="40" font-size="24">案件事实经过时间轴</text><text x="30" y="68" font-size="12">事件按日期精度排序，间距不表示时长；不确定日期单独保留，AI提取须复核。</text><path d="M40 100 V{max(100,y-30)}" stroke="#b8bdc3" fill="none"/>{"".join(elements)}</g></svg>'
    (folder/'事实时间轴.svg').write_text(svg,encoding='utf-8')

    import fitz
    pdf=fitz.open()
    page=None;cursor=0
    paragraphs=[('案件事实经过时间轴',16),(note,10)]
    for index,row in enumerate(graphic_rows,1):
        paragraphs.append((f'{index}. {row["date_text"] or "日期不明"} · {REVIEW[row["review_status"]]}',13))
        paragraphs.extend((text,10) for text in [row['actors']+' · '+row['description'],row['date_warning'],row['review_note']]+[ref['path']+' · '+display_locator(ref['path'],ref['locator'])+'：'+ref['quote'] for ref in row['evidence']] if text)
    for text,size in paragraphs:
        for raw_line in text.splitlines():
            for line in textwrap.wrap(raw_line,width=int(520/size),replace_whitespace=False,drop_whitespace=False) or ['']:
                if page is None or cursor+size*1.6>800:
                    page=pdf.new_page(width=595,height=842);cursor=42
                page.insert_text((36,cursor),line,fontname='china-s',fontsize=size,color=(.12,.13,.15))
                cursor+=size*1.6
        cursor+=8
    pdf.save(folder/'事实时间轴.pdf');pdf.close()
