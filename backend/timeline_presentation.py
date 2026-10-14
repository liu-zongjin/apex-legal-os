"""One presentation contract shared by previews and timeline delivery documents."""
import html
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
