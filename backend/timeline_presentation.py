"""One presentation contract shared by previews and timeline delivery documents."""
import html
import re
import textwrap
from .citation_locations import display_locator

STYLES={'axis':'纵向时间轴','table':'精简对照表','cards':'纪事卡片'}


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


def svg(events,settings=None,preview=False):
    rows,refs,settings=presentation(events,settings)
    total=len(rows)
    if preview:
        rows=rows[:8]
        used={number for row in rows for number in row['note_numbers']}
    else:used=set(range(1,len(refs)+1))
    pieces=[];y=112
    def label(x,y,text,size=13,bold=False):
        return f'<text x="{x}" y="{y}" font-size="{size}"'+(' font-weight="600"' if bold else '')+f'>{html.escape(text)}</text>'
    style=settings['style']
    if style=='table':
        pieces.append('<rect x="30" y="94" width="860" height="36" fill="#f2f4f7"/>')
        pieces += [label(44,117,'序号',12,True),label(95,117,'日期',12,True),label(270,117,'事实经过',12,True)];y=145
    for index,row in enumerate(rows,1):
        date=row['date_text'] or '日期不明';body=row['description']
        lines=[line for part in body.splitlines() for line in textwrap.wrap(part,width=45 if style!='cards' else 60,replace_whitespace=False,drop_whitespace=False)] or ['']
        if row['actors']:lines.extend(textwrap.wrap('主体：'+row['actors'],width=45 if style!='cards' else 60))
        dates=textwrap.wrap(date,width=13) or ['日期不明']
        note=''.join('['+str(number)+']' for number in row['note_numbers'])
        if style=='cards':
            height=70+len(lines)*22
            pieces.append(f'<rect x="30" y="{y-22}" width="860" height="{height}" rx="8" fill="#f6f7f9" stroke="#dde1e6"/>')
            # Full date/period is wrapped independently, never clipped.
            date_lines=textwrap.wrap(date,width=56)
            extra=(len(date_lines)-1)*24;height+=extra
            pieces[-1]=f'<rect x="30" y="{y-22}" width="860" height="{height}" rx="8" fill="#f6f7f9" stroke="#dde1e6"/>'
            for n,line in enumerate(date_lines):pieces.append(label(50,y+n*24,line,16,True))
            for n,line in enumerate(lines):pieces.append(label(50,y+32+extra+n*22,line))
            if note:pieces.append(label(50,y+36+extra+len(lines)*22,note,10))
        else:
            height=max(len(lines)*22+38,len(dates)*22+20)
            for n,line in enumerate(dates):pieces.append(label(95 if style=='table' else 32,y+n*22,line,13,True))
            if style=='axis':
                pieces.append(f'<path d="M224 {y-16} V{y+height}" stroke="#d0d5db"/><circle cx="224" cy="{y-4}" r="5" fill="#606770"/>')
            else:
                pieces.append(label(44,y,str(index),11));pieces.append(f'<path d="M30 {y+height-12} H890" stroke="#dde1e6"/>')
            for n,line in enumerate(lines):pieces.append(label(270,y+n*22,line))
            if note:pieces.append(label(270,y+len(lines)*22,note,10))
        y+=height+18
    if not rows:pieces.append(label(30,y,'没有纳入导出的事件'));y+=30
    if used:
        pieces.append(label(30,y+15,'原文依据',17,True));y+=48
        for number,ref in enumerate(refs,1):
            if number not in used:continue
            title=f'[{number}] '+ref['path']+(' · '+confirmed_position(ref) if confirmed_position(ref) else '')
            for line in textwrap.wrap(title,width=62):pieces.append(label(30,y,line,12,True));y+=21
            for part in ref['quote'].splitlines():
                for line in textwrap.wrap(part,width=65,replace_whitespace=False,drop_whitespace=False):pieces.append(label(30,y,line,12));y+=21
            y+=16
    subtitle=f'{STYLES[style]} · 日期保持原记录精度，间距不表示时长'
    if preview:subtitle+=f' · 前{len(rows)}项预览／共{total}项'
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="920" height="{max(220,y+30)}" viewBox="0 0 920 {max(220,y+30)}"><rect width="100%" height="100%" fill="white"/><g fill="#202327" font-family="Arial,SimSun,Songti SC,serif">'+label(30,42,'案件事实时间轴',23,True)+label(30,70,subtitle,12)+''.join(pieces)+'</g></svg>'


def pdf(events,settings,destination):
    import fitz
    rows,refs,settings=presentation(events,settings)
    escape=lambda text:html.escape(text).replace('\n','<br/>')
    style=settings['style'];blocks=['<h1>案件事实时间轴</h1><p class="caption">日期保持原记录精度，事件间距不表示时长。</p>']
    if style=='table':blocks.append('<table><tr><th>序号</th><th>日期</th><th>事实经过</th></tr>')
    elif style=='axis':blocks.append('<table>')
    for index,row in enumerate(rows,1):
        date=escape(row['date_text'] or '日期不明')
        body=escape(row['description'])+(' <sup>'+','.join(str(n) for n in row['note_numbers'])+'</sup>' if row['note_numbers'] else '')
        if row['actors']:body+='<p class="caption">主体：'+escape(row['actors'])+'</p>'
        if style=='cards':blocks.append(f'<div class="card"><h2>{date}</h2><p>{body}</p></div>')
        else:blocks.append('<tr>'+ (f'<td class="number">{index}</td>' if style=='table' else '')+f'<td class="date">{date}</td><td class="body">{body}</td></tr>')
    if style!='cards':blocks.append('</table>')
    if refs:
        blocks.append('<h2>原文依据</h2>')
        for number,ref in enumerate(refs,1):
            title=f'[{number}] '+ref['path']+(' · '+confirmed_position(ref) if confirmed_position(ref) else '')
            blocks.append('<p class="reference">'+escape(title)+'<br/>'+escape(ref['quote'])+'</p>')
    css='body{font-family:serif;font-size:10.5pt;color:#202327;line-height:1.35}h1{font-size:21pt;margin-bottom:10pt}h2{font-size:13pt}table{border-collapse:collapse;width:100%}th{background:#f2f4f7;text-align:left;font-size:9pt}td,th{padding:8pt 6pt;vertical-align:top}td{border-bottom:0.5pt solid #dde1e6}.date{width:100pt;font-weight:bold}.number{width:20pt}.caption{color:#606770;font-size:9pt}.card{background:#f6f7f9;padding:10pt;margin:0 0 12pt}.reference{font-size:9pt;margin-bottom:12pt}sup{font-size:8pt}'
    if style=='axis':css+='.body{border-left:1pt solid #d0d5db}.date{border-bottom:0}.body{border-bottom:0;padding-bottom:18pt}'
    story=fitz.Story(html=''.join(blocks),user_css=css)
    writer=fitz.DocumentWriter(str(destination))
    try:
        more=True;count=0
        while more:
            count+=1
            if count>2000:raise ValueError('导出页数过多，请分组导出')
            device=writer.begin_page(fitz.Rect(0,0,595,842))
            more,filled=story.place(fitz.Rect(36,42,559,800));story.draw(device);writer.end_page()
            if more and fitz.Rect(filled).is_empty:raise ValueError('内容无法分页，请分组导出')
    finally:writer.close()



def fishbone_pdf(events, sides, destination, include_evidence=True, conflict_ids=()):
    """Render the workbench's two-sided chronology with paginated source text."""
    import fitz
    from .case_timeline import numeric_claims_supported
    rows, _, _ = presentation(events, {'style':'axis','include_evidence':include_evidence})
    def unsupported(row):
        return not row.get('manual_unverified') and bool(row.get('evidence')) and not numeric_claims_supported(row.get('description',''),row['evidence'][0].get('quote',''))
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
    def runs(text):
        return re.findall(r'[\x00-\x7f]+|[^\x00-\x7f]+',text)
    def text_width(text,size):
        return sum((latin if ord(part[0])<128 else font).text_length(part,fontsize=size) for part in runs(text))
    def draw_text(x,baseline,text,size,color):
        for part in runs(text):
            ascii_run=ord(part[0])<128
            page.insert_text((x,baseline),part,fontname='helv' if ascii_run else 'china-s',fontsize=size,color=color)
            x+=(latin if ascii_run else font).text_length(part,fontsize=size)
    left_x,right_x,card_width,spine=36,432,374,421
    def wrap(value,size):
        result=[]
        for paragraph in str(value or '').split('\n'):
            line=''
            for char in paragraph:
                if line and text_width(line+char,size)>card_width-24:
                    result.append(line);line=char
                else:line+=char
            result.append(line)
        return result
    def lines(row):
        result=[]
        def add(text,size,color,step):
            for line in wrap(text,size):result.append((line,size,color,step))
        add(row.get('date_text') or '日期不明',16,(.10,.15,.24),25)
        status={'confirmed':'已确认','amended':'人工修改'}.get(row.get('review_status'),'')
        if row.get('review_status')=='pending' and (row.get('requires_review') is True or row['id'] in conflict_ids or unsupported(row) or row.get('date_precision')=='unknown'):status='待复核'
        if status:add(status,9,(.20,.45,.35) if status=='已确认' else (.61,.21,.20),15)
        if unsupported(row):add('数值与引文不一致',9,(.61,.21,.20),15)
        elif row['id'] in conflict_ids:add('有关联记录需对照',9,(.61,.21,.20),15)
        if row.get('actors'):add(row['actors'],10,(.10,.15,.24),16)
        add(row.get('description'),11,(.10,.15,.24),18)
        if include_evidence:
            for ref in row.get('evidence',[]):
                heading=(ref.get('party') or row.get('party') or '来源待确认')+' · '+(ref.get('document_type') or '案件材料')
                locator=confirmed_position(ref)
                add(heading,9,(.36,.43,.54),14)
                add(ref.get('path','')+(' · '+locator if locator else ''),9,(.36,.43,.54),14)
                add('“'+ref['quote']+'”' if ref.get('quote') else '手动关联文件，尚未定位原文',9,(.36,.43,.54),14)
        return result
    def new_page():
        nonlocal page,y
        page=doc.new_page(width=842,height=595);y=105
        page.insert_text((36,38),'案件事实时间轴',fontname='china-s',fontsize=20,color=(.10,.15,.24))
        page.insert_text((36,58),'日期保留原文精度；间距不表示时长。',fontname='china-s',fontsize=9,color=(.36,.43,.54))
        page.insert_text((160,84),'我方材料',fontname='china-s',fontsize=11,color=(.61,.21,.20))
        page.insert_text((520,84),'对方、其他方及待确认来源',fontname='china-s',fontsize=11,color=(.61,.21,.20))
        page.draw_line((spine,94),(spine,568),color=(.64,.27,.25),width=2)
    def take(queue,available):
        result=[];height=0
        while queue and height+queue[0][3]<=available:
            item=queue.pop(0);result.append(item);height+=item[3]
        return result,height
    def draw_card(x,entries,height,warning=False):
        if not entries:return
        page.draw_rect(fitz.Rect(x,y,x+card_width,y+height+20),color=(.64,.27,.25) if warning else (.84,.86,.89),fill=(.99,.97,.97) if warning else (.99,.99,.99),width=.7)
        cursor=y+11
        for text,size,color,step in entries:
            draw_text(x+12,cursor+size,text,size,color)
            cursor+=step
    new_page()
    for group in groups:
        left=next((item for item in group if side(item)=='client'),None)
        right=next((item for item in group if side(item)!='client'),None)
        left_lines=lines(left) if left else [];right_lines=lines(right) if right else []
        while left_lines or right_lines:
            available=550-y-20
            if available<35:new_page();available=550-y-20
            lchunk,lh=take(left_lines,available);rchunk,rh=take(right_lines,available)
            height=max(lh,rh)
            if not height:raise ValueError('时间轴内容无法分页')
            draw_card(left_x,lchunk,height,bool(left and (unsupported(left) or left['id'] in conflict_ids)));draw_card(right_x,rchunk,height,bool(right and (unsupported(right) or right['id'] in conflict_ids)))
            page.draw_circle((spine,y+13),4,color=(.61,.21,.20),fill=(1,1,1),width=2)
            if lchunk:page.draw_line((left_x+card_width,y+13),(spine-4,y+13),color=(.64,.27,.25),width=1)
            if rchunk:page.draw_line((spine+4,y+13),(right_x,y+13),color=(.64,.27,.25),width=1)
            y+=height+34
            if left_lines or right_lines:new_page()
    if not groups:page.insert_text((36,120),'没有纳入导出的事件',fontname='china-s',fontsize=11)
    try:doc.save(str(destination),garbage=3,deflate=True)
    finally:doc.close()
