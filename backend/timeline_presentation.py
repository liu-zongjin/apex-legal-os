"""One presentation contract shared by previews and timeline delivery documents."""
import html
import re
import textwrap
from .citation_locations import display_locator

STYLES = {'axis': '纵向时间轴', 'table': '精简对照表', 'cards': '纪事卡片'}
TITLE = '案件事实时间轴'
DATE_NOTE = '日期保留原记录精度，事件间距不表示时长。'

# Print colors are deliberately quiet. Date and source categories are always written out.
INK = '232832'
MUTED = '575F6C'
RULE = 'DDE0E5'
PAPER = 'F5F6F8'
ACCENT = '784746'
WHITE = 'FFFFFF'


def _summary(style, count, total=None):
    quantity = f'共 {count} 项事件' if total is None else f'前 {count} 项预览 / 共 {total} 项'
    return f'{STYLES[style]}  ·  {quantity}'


def options(value=None):
    value={} if value is None else value
    if not isinstance(value,dict) or set(value)-{'style','include_evidence'}:raise ValueError('导出选项无效')
    style=value.get('style','axis');include=value.get('include_evidence',True)
    if not isinstance(style,str) or style not in STYLES or not isinstance(include,bool):raise ValueError('请选择有效样式与原文依据选项')
    return {'style':style,'include_evidence':include}


def presentation(events,settings=None):
    settings=options(settings);visible=[row for row in events if row['review_status']!='excluded']
    references=[];keys={};rows=[]
    for row in visible:
        numbers=[]
        if settings['include_evidence']:
            for ref in row['evidence']:
                key=(ref['path'],ref['locator'],ref['quote'])
                if key not in keys:keys[key]=len(references)+1;references.append(ref)
                numbers.append(keys[key])
        rows.append({**row,'note_numbers':numbers})
    return rows,references,settings


def confirmed_position(ref):
    locator=display_locator(ref['path'],ref['locator'])
    return '' if any(word in locator for word in ('未取得','尚未确认','文本片段')) else locator


def svg(events, settings=None, preview=False):
    rows, refs, settings = presentation(events, settings)
    total = len(rows)
    if preview:
        rows = rows[:8]
    used = {number for row in rows for number in row['note_numbers']}
    style = settings['style']
    width, margin = 920, 36
    right, y = width - margin, 126
    content_x = margin + 205
    result = []

    def label(x, baseline, text, size=15, weight=400, color=INK, anchor='start'):
        result.append(f'<text x="{x}" y="{baseline}" font-size="{size}" font-weight="{weight}" '
                      f'fill="#{color}" text-anchor="{anchor}">{html.escape(text)}</text>')

    def line(x1, y1, x2, y2, color=RULE):
        result.append(f'<path d="M{x1} {y1} L{x2} {y2}" stroke="#{color}" fill="none"/>')

    def box(x, top, w, h, color, radius=0, stroke='none'):
        result.append(f'<rect x="{x}" y="{top}" width="{w}" height="{h}" rx="{radius}" fill="#{color}" stroke="{stroke}"/>')

    def wrap(text, maximum, size):
        # Use a full em per character as a conservative bound across installed CJK fonts.
        return [line for part in text.split('\n')
                for line in (textwrap.wrap(part, width=int(maximum / size), replace_whitespace=False,
                                            expand_tabs=False, drop_whitespace=False) or [''])]

    label(width // 2, 47, TITLE, size=27, weight=650, anchor='middle')
    label(width // 2, 73, _summary(style, len(rows), total if preview else None), size=14, color=MUTED, anchor='middle')
    label(width // 2, 95, DATE_NOTE, size=12, color=MUTED, anchor='middle')
    if style == 'table' and rows:
        box(margin, y, right - margin, 36, PAPER, radius=4)
        label(margin + 12, y + 23, '序号', size=13, weight=650)
        label(margin + 64, y + 23, '日期', size=13, weight=650)
        label(content_x, y + 23, '事实经过', size=13, weight=650)
        y += 36

    for index, row in enumerate(rows, 1):
        date = row['date_text'] or '日期不明'
        actor = f"主体  {row['actors']}" if row['actors'] else ''
        note = ' '.join(f'[{number}]' for number in row['note_numbers'])
        x = margin + 17 if style == 'cards' else content_x
        date_x = {'axis': margin, 'table': margin + 64, 'cards': x}[style]
        text_width = right - x - 17
        date_size = 18 if style == 'cards' else 15
        dates = wrap(date, text_width if style == 'cards' else content_x - date_x - 15, date_size)
        body = wrap(row['description'], text_width, 15)
        actors = wrap(actor, text_width, 12) if actor else []
        citations = wrap(note, text_width, 11) if note else []
        body_height = len(body) * 24 + len(actors) * 19 + len(citations) * 18
        date_height = len(dates) * 25
        height = 26 + (date_height + body_height + 8 if style == 'cards' else max(date_height, body_height))

        if style == 'cards':
            box(margin, y, right - margin, height, PAPER, radius=7, stroke=f'#{RULE}')
        elif style == 'table':
            if index % 2 == 0:
                box(margin, y, right - margin, height, PAPER)
            label(margin + 12, y + 26, str(index), 12, color=MUTED)
            line(margin, y + height, right, y + height)
        else:
            spine = content_x - 23
            line(spine, y, spine, y + height)
            result.append(f'<circle cx="{spine}" cy="{y + 21}" r="4.5" fill="#{WHITE}" stroke="#{ACCENT}" stroke-width="1.4"/>')

        for offset, value in enumerate(dates):
            label(date_x, y + 27 + offset * 25, value, date_size, 650)
        baseline = y + 27 + (date_height + 8 if style == 'cards' else 0)
        for value in body:
            label(x, baseline, value)
            baseline += 24
        for value in actors:
            label(x, baseline - 1, value, 12, color=MUTED)
            baseline += 19
        for value in citations:
            label(x, baseline - 1, value, 11, weight=650, color=ACCENT)
            baseline += 18
        y += height + (10 if style == 'cards' else 0)

    if not rows:
        label(margin, y + 14, '没有纳入导出的事件', color=MUTED)
        y += 36
    if used:
        y += 20
        line(margin, y, right, y)
        label(margin, y + 32, '原文依据', size=18, weight=650)
        y += 62
        for number, ref in enumerate(refs, 1):
            if number not in used:
                continue
            position = confirmed_position(ref)
            heading = f'[{number}] {ref["path"]}' + (f' · {position}' if position else '')
            for value in wrap(heading, right - margin, 13):
                label(margin, y, value, 13, weight=650)
                y += 20
            for value in wrap(ref['quote'], right - margin, 13):
                label(margin, y, value, 13, color=MUTED)
                y += 21
            y += 13
    height = max(220, y + 22)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{TITLE}" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/>'
            '<g xml:space="preserve" font-family="-apple-system, BlinkMacSystemFont, PingFang SC, Microsoft YaHei, Noto Sans CJK SC, Arial, sans-serif">'
            + ''.join(result) + '</g></svg>')


def pdf(events, settings, destination):
    import fitz

    rows, refs, settings = presentation(events, settings)
    style = settings['style']

    def escape(text):
        return html.escape(text).replace('\n', '<br/>')

    blocks = [f'<h1>{TITLE}</h1><p class="summary">{_summary(style, len(rows))}</p>',
              f'<p class="date-note">{DATE_NOTE}</p>']
    if rows and style == 'table':
        blocks.append('<table class="table"><thead><tr><th class="number">序号</th><th class="date">日期</th><th>事实经过</th></tr></thead><tbody>')
    elif rows and style == 'axis':
        blocks.append('<table class="axis"><tbody>')
    for index, row in enumerate(rows, 1):
        date_text = row['date_text'] or '日期不明'
        date = escape(date_text)
        marks = ','.join(str(number) for number in row['note_numbers'])
        fact = escape(row['description']) + (f' <sup>{marks}</sup>' if marks else '')
        actor = f'<p class="actor">主体 &nbsp; {escape(row["actors"])}</p>' if row['actors'] else ''
        body = f'<p class="fact">{fact}</p>{actor}'
        if style == 'cards':
            blocks.append(f'<div class="card"><h2>{date}</h2>{body}</div>')
        else:
            number = f'<td class="number">{index}</td>' if style == 'table' else ''
            alternate = ' class="alternate"' if style == 'table' and index % 2 == 0 else ''
            # Keep ordinary dates intact without letting an extended date
            # description dictate the width of the whole table.
            date = '<br/>'.join(escape(date_text[i:i + 14]) for i in range(0, len(date_text), 14))
            blocks.append(f'<tr{alternate}>{number}<td class="date">{date}</td><td class="event-body">{body}</td></tr>')
    if rows and style != 'cards':
        blocks.append('</tbody></table>')
    if not rows:
        blocks.append('<p class="actor">没有纳入导出的事件</p>')
    if refs:
        blocks.append('<h2 class="notes-heading">原文依据</h2>')
        for number, ref in enumerate(refs, 1):
            position = confirmed_position(ref)
            title = f'[{number}] {ref["path"]}' + (f' · {position}' if position else '')
            blocks.append(f'<p class="reference"><b>{escape(title)}</b><br/>{escape(ref["quote"])}</p>')

    css = f"""
        body {{font-family:sans-serif; font-size:10.5pt; line-height:1.5; color:#{INK}}}
        h1 {{font-size:23pt; font-weight:bold; margin:0 0 7pt; text-align:center}}
        h2 {{font-size:13pt; margin:0 0 5pt}}
        p {{margin:0}}
        .summary,.date-note {{text-align:center; color:#{MUTED}; font-size:9pt}}
        .date-note {{margin-bottom:19pt}}
        table {{border-collapse:collapse; width:100%; margin:0}}
        td,th {{padding:7pt 8pt; vertical-align:top; text-align:left}}
        th {{background:#{PAPER}; font-size:9.5pt; white-space:nowrap}}
        .table td {{border-bottom:.5pt solid #{RULE}}}
        .table .alternate td {{background:#{PAPER}}}
        .date {{font-weight:bold; white-space:nowrap}}
        .number {{text-align:center; color:#{MUTED}; font-size:9.5pt; white-space:nowrap}}
        .axis .date {{padding-left:0; border-right:1pt solid #{RULE}}}
        .axis .event-body {{padding-left:14pt; padding-bottom:13pt}}
        .actor {{font-size:9pt; color:#{MUTED}; margin:4pt 0 0}}
        .card {{background:#{PAPER}; border:.5pt solid #{RULE}; padding:10pt 12pt; margin:0 0 9pt}}
        .notes-heading {{margin:19pt 0 9pt; padding-top:7pt; border-top:.5pt solid #{RULE}}}
        .reference {{font-size:9pt; margin-bottom:9pt; color:#{MUTED}}}
        .reference b {{color:#{INK}}}
        sup {{font-size:8pt; color:#{ACCENT}}}
    """
    story = fitz.Story(html=''.join(blocks), user_css=css)
    writer = fitz.DocumentWriter(str(destination))
    try:
        more = True
        page = 0
        while more:
            page += 1
            if page > 2000:
                raise ValueError('导出页数过多，请分组导出')
            device = writer.begin_page(fitz.Rect(0, 0, 595, 842))
            more, filled = story.place(fitz.Rect(37, 39, 558, 790))
            story.draw(device)
            footer = fitz.Story(html=f'<p>第 {page} 页</p>', user_css=f'body{{margin:0}} p{{font-size:8pt;font-family:sans-serif;color:#{MUTED};text-align:right;margin:0}}')
            footer.place(fitz.Rect(37, 809, 558, 828))
            footer.draw(device)
            writer.end_page()
            if more and fitz.Rect(filled).is_empty:
                raise ValueError('内容无法分页，请分组导出')
    finally:
        writer.close()


def fishbone_pdf(events, sides, destination, include_evidence=True, conflict_ids=()):
    """Render the workbench's two-sided chronology with paginated source text."""
    import fitz
    from collections import deque
    from functools import lru_cache
    from .case_timeline import numeric_claims_supported
    rows, _, _ = presentation(events, {'style':'axis','include_evidence':include_evidence})
    def unsupported(row):
        return bool(row.get('evidence')) and not (row.get('manual_unverified') and not row['evidence'][0].get('quote')) and not numeric_claims_supported(row.get('description',''),row['evidence'][0].get('quote',''))
    def side(row):
        party=row.get('party') or (row.get('evidence') or [{}])[0].get('party')
        return sides.get(party,'unknown')
    groups=[];used=set()
    for row in rows:
        if row['id'] in used:continue
        used.add(row['id']);current=side(row);peer=None
        if row.get('sort_start') and row.get('sort_start')==row.get('sort_end') and row.get('topic') and current!='unknown':
            peer=next((other for other in rows if other['id'] not in used and other.get('sort_start')==row['sort_start'] and other.get('sort_end')==row['sort_end'] and other.get('topic')==row['topic'] and side(other) not in ('unknown',current)),None)
        if peer:used.add(peer['id'])
        groups.append([row,peer] if peer else [row])
    font=fitz.Font('china-s');latin=fitz.Font('helv');doc=fitz.open();page=None;y=0
    def rgb(hex_color):
        return tuple(int(hex_color[index:index + 2], 16) / 255 for index in (0, 2, 4))
    ink, muted, rule, paper, accent = map(rgb, (INK, MUTED, RULE, PAPER, ACCENT))
    def runs(text):
        return re.findall(r'[\x00-\x7f]+|[^\x00-\x7f]+',text)
    def text_width(text,size):
        return sum((latin if ord(part[0])<128 else font).text_length(part,fontsize=size) for part in runs(text))
    def draw_text(x,baseline,text,size,color):
        for part in runs(text):
            ascii_run=ord(part[0])<128
            page.insert_text((x,baseline),part,fontname='helv' if ascii_run else 'china-s',fontsize=size,color=color)
            x+=(latin if ascii_run else font).text_length(part,fontsize=size)
    left_x, right_x, card_width, spine = 38, 440, 364, 421
    content_top, content_bottom = 109, 546
    line_inset, vertical_inset = 12, 9

    @lru_cache(maxsize=4096)
    def char_width(char, size):
        return (latin if ord(char) < 128 else font).text_length(char, fontsize=size)

    def wrap(value,size):
        result=[]
        for paragraph in str(value or '').split('\n'):
            line = []
            width = 0
            for char in paragraph:
                step = char_width(char, size)
                if line and width + step > card_width - line_inset * 2:
                    result.append(''.join(line))
                    line = []
                    width = 0
                line.append(char)
                width += step
            result.append(''.join(line))
        return result
    def lines(row):
        result=[]
        def add(text,size,color,step):
            for line in wrap(text,size):result.append((line,size,color,step))
        add(row.get('date_text') or '日期不明', 15, ink, 23)
        status={'confirmed':'已确认','amended':'人工修改'}.get(row.get('review_status'),'')
        if row.get('review_status')=='pending' and (row.get('requires_review') is True or row['id'] in conflict_ids or unsupported(row) or row.get('date_precision')=='unknown'):status='待复核'
        if status:add(status, 9, muted, 14)
        if unsupported(row):add('数值与引文不一致', 9, accent, 15)
        elif row['id'] in conflict_ids:add('有关联记录需对照', 9, accent, 15)
        if row.get('actors'):add(row['actors'], 10, ink, 16)
        add(row.get('description'), 11, ink, 18)
        if include_evidence:
            for ref in row.get('evidence',[]):
                heading=(ref.get('party') or row.get('party') or '来源待确认')+' · '+(ref.get('document_type') or '案件材料')
                locator=confirmed_position(ref)
                result.append(('', 0, muted, 5))
                add(heading, 9, ink, 14)
                add(ref.get('path','')+(' · '+locator if locator else ''), 9, muted, 14)
                add('“'+ref['quote']+'”' if ref.get('quote') else ('手动关联文件夹，请自行核对材料' if ref.get('source_kind') == 'case_folder' else '手动关联文件，尚未定位原文'), 9, muted, 14)
        return result
    def new_page():
        nonlocal page,y
        page = doc.new_page(width=842, height=595)
        y = content_top
        subtitle = f'双侧时间轴  ·  共 {len(rows)} 项事件  ·  {DATE_NOTE}'
        draw_text(spine - text_width(TITLE, 21) / 2, 42, TITLE, 21, ink)
        draw_text(spine - text_width(subtitle, 9) / 2, 60, subtitle, 9, muted)
        for x, label in [(left_x, '我方材料'), (right_x, '对方、其他方及待确认来源')]:
            page.draw_rect(fitz.Rect(x, 74, x + card_width, 98), color=None, fill=paper)
            draw_text(x + (card_width - text_width(label, 10)) / 2, 90, label, 10, ink)
        page.draw_line((spine, 100), (spine, content_bottom), color=rule, width=1)
        page.draw_line((left_x, 557), (right_x + card_width, 557), color=rule, width=.5)
        page_number = f'第 {len(doc)} 页'
        draw_text(right_x + card_width - text_width(page_number, 8), 573, page_number, 8, muted)
    def take(queue,available):
        result=[];height=0
        while queue and height+queue[0][3]<=available:
            item=queue.popleft();result.append(item);height+=item[3]
        return result,height
    def draw_card(x,entries,height,warning=False):
        if not entries:return
        page.draw_rect(fitz.Rect(x, y, x + card_width, y + height + vertical_inset * 2),
                       color=accent if warning else rule, fill=paper if warning else (1, 1, 1), width=.6)
        cursor = y + vertical_inset
        for text,size,color,step in entries:
            if text:
                draw_text(x + line_inset, cursor + size, text, size, color)
            cursor+=step
    new_page()
    for group in groups:
        left=next((item for item in group if side(item)=='client'),None)
        right=next((item for item in group if side(item)!='client'),None)
        left_lines = deque(lines(left) if left else [])
        right_lines = deque(lines(right) if right else [])
        total_height = max(sum(line[3] for line in left_lines), sum(line[3] for line in right_lines))
        capacity = content_bottom - content_top - vertical_inset * 2
        if y > content_top and total_height > content_bottom - y - vertical_inset * 2:
            new_page()
        continuing = False
        while left_lines or right_lines:
            available = min(capacity, content_bottom - y - vertical_inset * 2)
            continuation = ('续上页', 8.5, muted, 16)
            lchunk, lh = take(left_lines, available - (continuation[3] if continuing else 0))
            rchunk, rh = take(right_lines, available - (continuation[3] if continuing else 0))
            if continuing and lchunk:
                lchunk.insert(0, continuation)
                lh += continuation[3]
            if continuing and rchunk:
                rchunk.insert(0, continuation)
                rh += continuation[3]
            height=max(lh,rh)
            if not height:raise ValueError('时间轴内容无法分页')
            draw_card(left_x,lchunk,lh,bool(left and (unsupported(left) or left['id'] in conflict_ids)))
            draw_card(right_x,rchunk,rh,bool(right and (unsupported(right) or right['id'] in conflict_ids)))
            junction = y + 16
            page.draw_circle((spine,junction),3.3,color=accent,fill=(1,1,1),width=1.1)
            if lchunk:page.draw_line((left_x+card_width,junction),(spine-3.3,junction),color=rule,width=.7)
            if rchunk:page.draw_line((spine+3.3,junction),(right_x,junction),color=rule,width=.7)
            y += height + vertical_inset * 2 + 11
            if left_lines or right_lines:
                new_page()
                continuing = True
    if not groups:page.insert_text((36,120),'没有纳入导出的事件',fontname='china-s',fontsize=11)
    try:doc.save(str(destination),garbage=3,deflate=True)
    finally:doc.close()
