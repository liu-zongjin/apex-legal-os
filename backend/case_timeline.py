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
CATEGORIES={'诉讼程序','合同订立','履行付款','交付验收','沟通通知','财产处置','其他'}

def numeric_claims_supported(description, quote):
    """Reject changed numeric facts; exact numeric tokens prevent 10 matching 10000."""
    def numbers(text):
        text=re.sub(r'(?<=\d)[,，](?=\d{3}(?:\D|$))','',str(text))
        return set(re.findall(r'(?<![\d.])\d+(?:\.\d+)?(?![\d.])',text))
    return numbers(description) <= numbers(quote)


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
    if not numeric_claims_supported(description, quote):
        return None
    date_text=plain(proposal.get('date_text',''),100)
    warning=''
    if date_text and date_text not in quote:
        date_text='';warning='AI日期未出现在引句中，未采用；请回看原件。'
    actors=plain(proposal.get('actors',''),300)
    if actors and actors not in source['text']:
        actors=''
    ref={key:source[key] for key in ('id','path','sha256','locator','chunk_index')}
    ref['party']=source.get('party','待确认')
    ref['document_type']=source.get('document_type','案件材料')
    ref['vision']=bool(source.get('vision'))
    ref['quote']=quote
    identifier=hashlib.sha256(json.dumps([source['path'],source['locator'],quote,date_text,description,actors,proposal.get('topic','')],ensure_ascii=False).encode()).hexdigest()[:24]
    return {'id':identifier,'description':description,'actors':actors,'date_text':date_text,
            'topic':plain(proposal.get('topic',''),200), 'category':proposal.get('category') if isinstance(proposal.get('category'),str) and proposal.get('category') in CATEGORIES else '其他', 'party':ref['party'], 'document_type':ref['document_type'], **date_bounds(date_text),
            'date_warning':warning or date_bounds(date_text)['date_warning'],
            'evidence':[ref],'review_status':'pending','review_note':'', 'requires_review':proposal.get('requires_review') is not False or ref['vision'], 'original':{'date_text':date_text,'description':description,'actors':actors}}


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
        if len(bounds)>1:continue  # A broad topic and actor cannot identify a single occurrence.
        result.append({'type':'possible_duplicate',
            'label':'可能重复的事件，保留各份材料的记录',
            'event_ids':[row['id'] for row in rows]})
    return result


def review_events(events,updates,party_subjects=None):
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
        extracted = original['original']
        source_actor = original.get('actors_default') or ''
        if update.get('use_source_actor') is True:
            ref = next(iter(original.get('evidence', ())), {})
            candidate = (party_subjects or {}).get(ref.get('party') or original.get('party'))
            if (not candidate or actors != candidate or original.get('actors') or extracted.get('actors')
                    or original.get('actors_edited') or source_actor or not ref or ref.get('source_kind') == 'case_folder'):
                raise HTTPException(409, '文书来源方或事件主体已变化，请重新载入复核')
            source_actor = candidate
        changed = (description != extracted['description'] or date_text != extracted['date_text']
                   or actors != (source_actor or extracted['actors']))
        if not description or ((changed or status in {'amended','excluded'}) and not note):raise HTTPException(422,'修改或排除事件时请填写复核意见')
        if changed and status not in {'amended','excluded'}:raise HTTPException(422,'修改了事件内容，请标记人工修改并填写意见')
        row={**original,**date_bounds(date_text),'date_text':date_text,'description':description,'actors':actors,'review_status':status,'review_note':note}
        if source_actor:
            row['actors_default'] = source_actor
        if update.get('actors_edited') is True:
            row['actors_edited'] = True
        if status == 'excluded' and original['review_status'] != 'excluded':
            row['before_delete_status'] = original['review_status']
            row['before_delete_note'] = original.get('review_note', '')
        elif status != 'excluded' and original['review_status'] == 'excluded':
            row.pop('before_delete_status', None)
            row.pop('before_delete_note', None)
        if date_text and not row.get('manual_unverified') and not any(date_text in ref['quote'] for ref in row['evidence']):row['date_warning']='人工日期与原始引句不同，请结合复核意见核对。'
        output.append(row)
    return ordered(output)


def artifacts(job,folder):
    from openpyxl import Workbook
    from .case_timeline_document import write_document
    from .timeline_presentation import DATE_NOTE, TITLE, presentation, svg, pdf, confirmed_position
    events=ordered(job['timeline_events']);active={row['id'] for row in events if row['review_status']!='excluded' and row.get('evidence') and numeric_claims_supported(row.get('description',''),row['evidence'][0].get('quote',''))}
    conflicts=[{**item,'event_ids':[event_id for event_id in item.get('event_ids',[]) if event_id in active]}
               for item in job.get('timeline_conflicts',[])]
    job['timeline_issues']=issues(events)+[item for item in conflicts if len(item['event_ids']) >= 2]
    rows,refs,settings=presentation(events,job.get('export_options'));job['export_options']=settings
    wb=Workbook();ws=wb.active;ws.title='事实经过';ws.append(['序号','日期','主体','事实经过']+(['尾注'] if settings['include_evidence'] else []))
    lines=[f'# {TITLE}', f'共 {len(rows)} 项事件。{DATE_NOTE}']
    for index,row in enumerate(rows,1):
        markers='、'.join(str(n) for n in row['note_numbers'])
        ws.append([index,row['date_text'] or '日期不明',row['actors'],row['description']]+([markers] if settings['include_evidence'] else []))
        lines.append(f'## {index}. {row["date_text"] or "日期不明"}')
        if row['actors']:lines.append('**主体**  '+row['actors'])
        lines.append(row['description']+''.join(f'[^{n}]' for n in row['note_numbers']))
    _style_timeline_sheet(ws, [9, 24, 24, 92] + ([12] if settings['include_evidence'] else []), {1, 2, 5})
    if refs:
        notes=wb.create_sheet('原文依据');notes.append(['尾注编号','来源文件','已核实位置','原文引句'])
        for number,ref in enumerate(refs,1):
            notes.append([number,ref['path'],confirmed_position(ref),ref['quote']])
            lines.append(f'[^{number}]: '+ref['path']+(' · '+confirmed_position(ref) if confirmed_position(ref) else '')+'\n    '+ref['quote'].replace('\n','\n    '))
        _style_timeline_sheet(notes, [12, 44, 24, 92], {1})
    wb.save(folder/'事实经过表.xlsx')
    write_document(events,folder/'事实经过表.docx',REVIEW,settings)
    (folder/'事实经过.md').write_text('\n\n'.join(lines),encoding='utf-8')
    from .case_workflows import public_job
    audit = public_job(job)
    (folder/'时间轴核验底稿.json').write_text(json.dumps({key:audit.get(key) for key in ('case_id','revision','sources','timeline_events','timeline_issues','timeline_coverage','claims','results','export_options')},ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'事实时间轴.svg').write_text(svg(events,settings),encoding='utf-8')
    pdf(events,settings,folder/'事实时间轴.pdf')


def _style_timeline_sheet(sheet, widths, centered_columns):
    from math import ceil
    from unicodedata import east_asian_width
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from .timeline_presentation import ACCENT, INK, MUTED, PAPER, RULE, WHITE

    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_title_rows = '1:1'
    sheet.oddFooter.right.text = '第 &P 页'
    sheet.row_dimensions[1].height = 27
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    edge = Border(bottom=Side(style='hair', color=RULE))
    header_font = Font(name='Calibri', size=11, bold=True, color=WHITE)
    cell_font = Font(name='Calibri', size=11, color=INK)
    meta_font = Font(name='Calibri', size=10, color=MUTED)
    header_fill = PatternFill('solid', fgColor=ACCENT)
    alternate_fill = PatternFill('solid', fgColor=PAPER)
    for index, cells in enumerate(sheet.iter_rows(), 1):
        max_lines = 1
        for cell, width in zip(cells, widths):
            centered = cell.column in centered_columns
            if index == 1:
                cell.font = header_font
                cell.fill = header_fill
                continue
            cell.font = meta_font if centered else cell_font
            cell.border = edge
            if index % 2 == 1:
                cell.fill = alternate_fill
            if isinstance(cell.value, str):
                cell.data_type = 's'
                chars_per_line = max(1, int(width * .93) - (1 if centered else 3))
                lines = sum(max(1, ceil(sum(2 if east_asian_width(char) in 'WF' else 1 for char in line)
                                        / chars_per_line)) for line in cell.value.split('\n'))
                max_lines = max(max_lines, lines)
        vertical = 'center' if max_lines <= 2 else 'top'
        for cell in cells:
            centered = cell.column in centered_columns
            cell.alignment = Alignment(wrap_text=True, vertical=vertical, horizontal='center' if centered else 'left',
                                       indent=0 if centered else 1)
        if index > 1:
            sheet.row_dimensions[index].height = min(409, max(27, max_lines * 15 + 9))
