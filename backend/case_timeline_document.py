"""Readable chronology table with indexed original citations, without changing event text."""
from .citation_locations import display_locator
from docx import Document
from docx.shared import Mm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _text(paragraph, text, size=10.5, bold=False, color='202327'):
    run=paragraph.add_run(text)
    run.font.name='Arial'
    run.font.size=Pt(size)
    run.font.bold=bold
    run.font.color.rgb=RGBColor.from_string(color)
    fonts=run._element.get_or_add_rPr().rFonts
    fonts.set(qn('w:eastAsia'),'SimSun')
    paragraph.paragraph_format.space_after=Pt(3)
    paragraph.paragraph_format.line_spacing=1.18
    return paragraph


def _cell_paragraph(cell, text, first=False, **kwargs):
    paragraph=cell.paragraphs[0] if first else cell.add_paragraph()
    return _text(paragraph,text,**kwargs)


def write_document(events, destination, review_labels):
    doc=Document()
    section=doc.sections[0]
    section.page_width=Mm(210);section.page_height=Mm(297)
    section.top_margin=Mm(18);section.bottom_margin=Mm(18)
    section.left_margin=Mm(18);section.right_margin=Mm(18)
    section.footer_distance=Mm(9)
    for name,size in [('Normal',10.5),('Title',21),('Heading 1',14),('Heading 2',11)]:
        style=doc.styles[name];style.font.name='Arial';style.font.size=Pt(size)
        style.font.color.rgb=RGBColor(0,0,0)
        style.paragraph_format.space_after=Pt(6)
        for border in list(style.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
    title=doc.add_paragraph(style='Title');_text(title,'案件事实经过表',size=21)
    title.paragraph_format.space_after=Pt(8)
    _text(doc.add_paragraph(),f'共 {len(events)} 项事件    日期与事件保持原始记录或已保存的人工修订',size=9,color='606770')
    _text(doc.add_paragraph(),'年月及期间仅用于排序，不代表具体发生日；日期不明项不参与先后判断。复核状态不等同于事实已获裁判认定。',size=9,color='606770')
    references=[];numbers={}
    def reference_number(ref):
        key=(ref['path'],ref['locator'],ref['quote'])
        if key not in numbers:
            numbers[key]=f'引文 {len(references)+1}';references.append((numbers[key],ref))
        return numbers[key]
    table=doc.add_table(rows=1,cols=4);table.autofit=False
    widths=[11,37,102,24]
    for column,width in zip(table.columns,widths):column.width=Mm(width)
    properties=table._tbl.tblPr
    borders=OxmlElement('w:tblBorders')
    for edge in ['top','left','bottom','right','insideV','insideH']:
        element=OxmlElement('w:'+edge);element.set(qn('w:val'),'single' if edge=='insideH' else 'nil')
        element.set(qn('w:sz'),'4');element.set(qn('w:color'),'DDE1E6');borders.append(element)
    properties.append(borders)
    margins=OxmlElement('w:tblCellMar')
    for edge,value in [('top',100),('bottom',110),('left',80),('right',80)]:
        item=OxmlElement('w:'+edge);item.set(qn('w:w'),str(value));item.set(qn('w:type'),'dxa');margins.append(item)
    properties.append(margins)
    repeat=OxmlElement('w:tblHeader');table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for cell,width,label in zip(table.rows[0].cells,widths,['序号','日期','事实经过与依据','复核状态']):
        cell.width=Mm(width);_cell_paragraph(cell,label,first=True,size=9,bold=True)
        shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'F2F4F7');cell._tc.get_or_add_tcPr().append(shade)
    for index,event in enumerate(events,1):
        cells=table.add_row().cells
        for cell,width in zip(cells,widths):cell.width=Mm(width)
        _cell_paragraph(cells[0],str(index),first=True,size=9,color='606770')
        _cell_paragraph(cells[1],event['date_text'] or '日期不明',first=True,size=10,bold=True)
        _cell_paragraph(cells[2],event['description'],first=True)
        refs=[reference_number(ref) for ref in event['evidence']]
        _cell_paragraph(cells[2],('主体  '+event['actors']+'    ' if event['actors'] else '')+'原文依据  '+'、'.join(refs),size=9,color='606770')
        if event['review_note']:_cell_paragraph(cells[2],'复核意见  '+event['review_note'],size=9)
        if event['date_warning']:_cell_paragraph(cells[2],event['date_warning'],size=9,color='606770')
        _cell_paragraph(cells[3],review_labels[event['review_status']],first=True,size=9,color='606770')
        # Prevent short events splitting across pages. Long legal text may paginate.
        if sum(len(p.text) for cell in cells for p in cell.paragraphs)<450:
            keep=OxmlElement('w:cantSplit');table.rows[-1]._tr.get_or_add_trPr().append(keep)
    doc.add_page_break()
    _text(doc.add_paragraph(style='Heading 1'),'原文依据',size=14,bold=True)
    _text(doc.add_paragraph(),'“引文”是主表引用的原文条目，“材料”是来源文件。按编号查找下列原文；页码仅在取得可核验位置时显示。',size=9,color='606770')
    sources={}
    for _,ref in references:
        if ref['path'] not in sources:sources[ref['path']]=f'材料 {len(sources)+1}'
    for path,code in sources.items():
        _text(doc.add_paragraph(),code+'  '+path,size=9,color='606770')
    for number,ref in references:
        heading=_text(doc.add_paragraph(),number+'    来自'+sources[ref['path']],size=10,bold=True)
        heading.paragraph_format.keep_with_next=True
        location=_text(doc.add_paragraph(),'位置  '+display_locator(ref['path'],ref['locator']),size=9,color='606770')
        location.paragraph_format.keep_with_next=True
        heading.paragraph_format.keep_with_next=True
        quote=_text(doc.add_paragraph(),ref['quote'],size=10)
        quote.paragraph_format.space_after=Pt(10)
        if len(ref['quote'])<450:quote.paragraph_format.keep_together=True
    footer=section.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    _text(footer,'第 ',size=8,color='606770')
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    _text(footer,' 页',size=8,color='606770')
    doc.core_properties.author='';doc.core_properties.last_modified_by=''
    doc.save(destination)
