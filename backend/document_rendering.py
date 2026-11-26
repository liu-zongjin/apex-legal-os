"""Shared Word renderers for standalone documents, bundles, and case filing."""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Callable, List, Optional

from pydantic import BaseModel

from .appearance import get_appearance, logo_stream
from .cause_catalog import document_cause_label


class SuohanRequest(BaseModel):
    court: str
    clients: List[str]
    lawyers: List[str]
    parties: List[str]
    caseType: str
    caseNo: str = ""  # 案号（可选）
    stages: List[str]
    date: str
    lawyerContacts: List[dict]
    format: str = "word"  # word 或 pdf


class PowerAttorneyRequest(BaseModel):
    clientType: str  # legal 或 natural
    clientName: str
    creditCode: str = ""
    address: str = ""
    legalRepresentative: str = ""
    idCard: str = ""
    stages: Optional[List[str]] = None  # 代理阶段（文书合集传入，如 一审、二审）
    lawyers: List[dict]
    parties: List[str]
    caseType: str = ""
    caseNumber: str = ""
    entrustType: str
    authorityContent: Optional[List[str]] = None
    date: str


class RepIdentityCertRequest(BaseModel):
    clientName: str  # 委托人名称
    repName: str     # 法定代表人姓名
    repTitle: str    # 法定代表人职务
    date: str        # 落款日期


def generate_suohan_docx(data: SuohanRequest, *, get_db: Callable[[], sqlite3.Connection]) -> bytes:
    """生成所函 Word 文档"""
    from docx import Document
    from docx.shared import Pt, Inches, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    profile = get_appearance(get_db)
    doc = Document()

    # 设置页面尺寸（A4）和边距
    sections = doc.sections
    for section in sections:
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.17)
        section.right_margin = Cm(3.17)

    # 添加律所Logo（如果存在）- 宽度4.8英寸（放大50%）
    logo_path = logo_stream(profile)
    if logo_path is not None:
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        run.add_picture(logo_path, width=Inches(4.8))

    # 标题
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(12)
    run = title.add_run(profile["firm_name"] + "函")
    run.font.size = Pt(24)
    run.font.bold = True
    run.font.name = '方正小标宋简体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '方正小标宋简体')

    # 函号（带下划线）- 格式：（    ）粤明思函字第____（  ）号
    header_para = doc.add_paragraph()
    header_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header_para.paragraph_format.space_after = Pt(12)
    run = header_para.add_run("（    ）" + profile["firm_code"] + "函字第")
    run.font.size = Pt(12)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    # 下划线空格（8个空格）
    run = header_para.add_run("        ")
    run.font.size = Pt(12)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.underline = True
    run = header_para.add_run("（  ）号")
    run.font.size = Pt(12)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 法院名称（带下划线）- 格式：佛山市中级人民法院：
    # data.court 已含"法院"/"法庭"等后缀时只追加"："，否则追加"法院："
    court_name = data.court
    _court_suffixes = ("法院", "法庭", "仲裁委员会", "仲裁院", "仲裁委", "检察院")
    _court_suffix = "：" if any(court_name.endswith(s) for s in _court_suffixes) else "法院："
    court_para = doc.add_paragraph()
    court_para.paragraph_format.space_after = Pt(12)
    run = court_para.add_run(court_name)
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.underline = True
    run = court_para.add_run(_court_suffix)
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 正文段落 - 首行缩进2字符，行距固定值28磅（约2倍）
    clients_text = "、".join(data.clients)
    lawyers_text = "、".join(data.lawyers)
    parties_text = "、".join(data.parties) if data.parties else "对方当事人"
    stages_text = "、".join(data.stages)

    body_para = doc.add_paragraph()
    body_para.paragraph_format.first_line_indent = Cm(0.74)  # 首行缩进2字符
    body_para.paragraph_format.line_spacing = Pt(28)  # 固定值28磅
    body_para.paragraph_format.space_after = Pt(0)

    # 本所依法接受
    run = body_para.add_run("本所依法接受")
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 委托人（下划线）
    run = body_para.add_run(clients_text)
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.underline = True

    run = body_para.add_run("的委托，依法指派本所")
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 律师（下划线）
    run = body_para.add_run(lawyers_text)
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.underline = True

    run = body_para.add_run("律师在委托人与")
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 当事人（下划线）
    run = body_para.add_run(parties_text)
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.underline = True

    run = body_para.add_run("的")
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 案由（下划线）
    run = body_para.add_run(data.caseType)
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.underline = True

    # 案号（如果有）- 格式：【案号：（2026）粤06民终1438号】
    if data.caseNo:
        run = body_para.add_run("【案号：")
        run.font.size = Pt(14)
        run.font.name = '宋体'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        run = body_para.add_run(data.caseNo)
        run.font.size = Pt(14)
        run.font.name = '宋体'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        run.font.underline = True
        run = body_para.add_run("】")
        run.font.size = Pt(14)
        run.font.name = '宋体'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    run = body_para.add_run("一案中，担任")
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 代理阶段（下划线）
    run = body_para.add_run(stages_text)
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.underline = True

    run = body_para.add_run("阶段委托人的代理人。")
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 特此函告
    notice_para = doc.add_paragraph()
    notice_para.paragraph_format.first_line_indent = Cm(0.74)
    notice_para.paragraph_format.line_spacing = Pt(28)
    notice_para.paragraph_format.space_before = Pt(0)
    notice_para.paragraph_format.space_after = Pt(0)
    run = notice_para.add_run("特此函告！")
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 以下无正文
    no_text_para = doc.add_paragraph()
    no_text_para.paragraph_format.first_line_indent = Cm(0.74)
    no_text_para.paragraph_format.line_spacing = Pt(28)
    no_text_para.paragraph_format.space_before = Pt(0)
    no_text_para.paragraph_format.space_after = Pt(0)
    run = no_text_para.add_run("（以下无正文）")
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 空行（用于落款前的间距）
    for _ in range(2):
        doc.add_paragraph()

    # 落款 - 律所名称（右对齐）
    signature_para = doc.add_paragraph()
    signature_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    signature_para.paragraph_format.line_spacing = Pt(28)
    signature_para.paragraph_format.space_after = Pt(0)
    run = signature_para.add_run(profile["firm_name"])
    run.font.size = Pt(16)
    run.font.bold = True
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 日期（右对齐）
    date_para = doc.add_paragraph()
    date_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    date_para.paragraph_format.line_spacing = Pt(28)
    date_para.paragraph_format.space_after = Pt(12)
    run = date_para.add_run(data.date)
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 经办律师信息（左对齐，带下划线）
    for contact in data.lawyerContacts:
        if contact.get('name'):
            lawyer_para = doc.add_paragraph()
            lawyer_para.paragraph_format.line_spacing = Pt(28)
            lawyer_para.paragraph_format.space_after = Pt(0)
            run = lawyer_para.add_run("经办律师：")
            run.font.size = Pt(14)
            run.font.name = '宋体'
            run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
            run = lawyer_para.add_run(contact['name'])
            run.font.size = Pt(14)
            run.font.name = '宋体'
            run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
            run.font.underline = True

            phone_para = doc.add_paragraph()
            phone_para.paragraph_format.line_spacing = Pt(28)
            phone_para.paragraph_format.space_after = Pt(0)
            run = phone_para.add_run("联系电话：")
            run.font.size = Pt(14)
            run.font.name = '宋体'
            run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
            if contact.get('phone'):
                run = phone_para.add_run(contact['phone'])
                run.font.size = Pt(14)
                run.font.name = '宋体'
                run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
                run.font.underline = True

    # 地址
    addr_para = doc.add_paragraph()
    addr_para.paragraph_format.line_spacing = Pt(28)
    addr_para.paragraph_format.space_after = Pt(0)
    run = addr_para.add_run("地    址：" + profile["firm_address"])
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 办公电话
    office_para = doc.add_paragraph()
    office_para.paragraph_format.line_spacing = Pt(28)
    office_para.paragraph_format.space_after = Pt(0)
    run = office_para.add_run("办公电话：" + profile["firm_phone"])
    run.font.size = Pt(14)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 保存到内存
    from io import BytesIO
    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return output.getvalue()


def generate_power_attorney_docx(data: PowerAttorneyRequest, *, get_db: Callable[[], sqlite3.Connection], frontend_dir: Path) -> bytes:
    """生成授权委托书 Word 文档 - 严格按截图格式（仿宋正文/宋体标题）"""
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    def add_run_fs(p, text, size=14, font='FangSong', bold=False, underline=False):
        """添加一个run，字体默认FangSong（仿宋），标题用SimSun（宋体）"""
        run = p.add_run(text)
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.name = font
        run._element.rPr.rFonts.set(qn('w:eastAsia'), font)
        if underline:
            run.underline = True
        return run

    profile = get_appearance(get_db)
    doc = Document()

    # 页面尺寸（A4）和边距
    for section in doc.sections:
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.17)
        section.right_margin = Cm(3.17)

    # ═══ 标题：居中、22pt、加粗、宋体 ═══
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(8)  # 减小段后间距，避免分页过多
    title.paragraph_format.line_spacing = Pt(25)
    r = title.add_run("授权委托书")
    r.font.size = Pt(22)
    r.font.bold = True
    r.font.name = '宋体'
    r._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    is_legal = data.clientType == 'legal'

    # ═══ 委托人信息区域（每段固定行距25pt，无额外段后距）═══
    def make_body_para(space_after=0):
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = Pt(25)
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.space_before = Pt(0)
        return p

    # 委托人名称 - 去掉下划线
    p = make_body_para()
    add_run_fs(p, "委托人：")
    add_run_fs(p, data.clientName)

    if is_legal:
        p = make_body_para()
        add_run_fs(p, "统一社会信用代码：")
        add_run_fs(p, data.creditCode or '')

        p = make_body_para()
        add_run_fs(p, "住所地：")
        add_run_fs(p, data.address or '')

        p = make_body_para(space_after=12)
        add_run_fs(p, "法定代表人：")
        add_run_fs(p, data.legalRepresentative or '')
    else:
        p = make_body_para()
        add_run_fs(p, "公民身份号码：")
        add_run_fs(p, data.idCard or '')

        p = make_body_para(space_after=10)
        add_run_fs(p, "住所地：")
        add_run_fs(p, data.address or '')

    # ═══ 受委托人区域 ═══
    for lawyer in data.lawyers:
        if lawyer.get('name'):
            p = make_body_para()
            add_run_fs(p, "受委托人：")
            add_run_fs(p, lawyer['name'], underline=True)
            add_run_fs(p, "律师，联系电话：")
            add_run_fs(p, lawyer.get('phone', ''), underline=True)
            add_run_fs(p, "。")

    # 工作单位
    p = make_body_para(space_after=10)
    add_run_fs(p, "工作单位：" + profile["firm_name"] + "，地址：" + profile["firm_address"] + "。")

    # ═══ 委托权限内容定义 ═══
    authority_content = {
        'plaintiff': {
            'stage': '一审',
            'authorities': [
                '代为申请财产保全；',
                '代为起诉、出庭；',
                '代为收集、提供证据，进行辩论；',
                '代为查阅本案有关材料；',
                '代为提出回避申请、管辖权异议申请；',
                '代为签署、递交、接收法律文书；',
                '代为上诉，进行和解，请求调解，提起反诉。'
            ]
        },
        'defendant': {
            'stage': '一审',
            'authorities': [
                '代为应诉、答辩、出庭；',
                '代为收集、提供证据，进行辩论；',
                '代为查阅本案有关材料；',
                '代为提出回避申请、管辖权异议申请；',
                '代为签署、递交、接收法律文书；',
                '代为提起反诉或上诉；',
                '代为进行和解，请求调解。'
            ]
        },
        'appellant': {
            'stage': '二审',
            'authorities': [
                '代为上诉、答辩、出庭；',
                '代为收集、提供证据，进行辩论；',
                '代为查阅本案有关材料；',
                '代为提出回避申请、管辖权异议申请；',
                '代为签署、递交、接收法律文书；',
                '代为承认、变更、放弃上诉请求，代为进行和解，请求调解。'
            ]
        },
        'appellee': {
            'stage': '二审',
            'authorities': [
                '代为答辩、出庭；',
                '代为收集、提供证据，进行辩论；',
                '代为查阅本案有关材料；',
                '代为提出回避申请、管辖权异议申请；',
                '代为签署、递交、接收法律文书；',
                '代为进行和解，请求调解。'
            ]
        },
        'arbApplicant': {
            'stage': '仲裁',
            'authorities': [
                '代为提起仲裁、出庭；',
                '代为选择仲裁员；',
                '代为收集、提供证据，进行辩论；',
                '代为查阅本案有关材料；',
                '代为提出回避申请、主管权异议申请；',
                '代为签署、递交、接收法律文书；',
                '代为和解，请求调解。'
            ]
        },
        'arbRespondent': {
            'stage': '仲裁',
            'authorities': [
                '代为应诉（裁）、出庭；',
                '代为选择仲裁员；',
                '代为收集、提供证据，进行辩论；',
                '代为查阅本案有关材料；',
                '代为提出回避申请；',
                '代为签署、递交、接收法律文书；',
                '代为和解，请求调解。'
            ]
        },
        'execApplicant': {
            'stage': '强制执行',
            'authorities': [
                '代为申请强制执行、参与执行程序、代为协助法院执行；',
                '代为调解或执行和解；',
                '代为签收相关法律文件；',
                '代为领取案款；',
                '代为投诉、提出申诉、控告；',
                '代为参与执行相关的活动；代为查阅、复制档案等。'
            ]
        },
        'execRespondent': {
            'stage': '强制执行',
            'authorities': [
                '代为调查取证；',
                '代为提出回避申请；',
                '代为参加执行和解、执行调解；',
                '代为提出执行异议及复议；',
                '代为提出申诉、投诉、举报、控告；',
                '代为签署、递交、接收法律文书。'
            ]
        },
        'execObjection': {
            'stage': '执行异议',
            'authorities': [
                '代为提出执行异议申请（申请排除执行）；',
                '代为出庭接受询问；',
                '代为收集、提供证据，进行辩论；',
                '代为查阅本案有关材料；',
                '代为承认、变更、放弃异议申请；',
                '代为签署、递交、接收法律文书。'
            ]
        },
        'bankruptcy': {
            'stage': '破产清算',
            'authorities': [
                '申报债权、对债权审核意见提出异议；',
                '进行调解、和解；',
                '参加债权人会议、行使表决权；',
                '审查/表决重整计划（草案）、财产处置方案、分配方案等各项方案议案，提出异议或意见；',
                '参与财产分配，领取分配所得；',
                '提交、签收有关法律文件；',
                '其他与破产有关的事宜。'
            ]
        }
    }

    # 空行
    doc.add_paragraph()

    # ═══ 主文内容 - 按截图格式，首行缩进2字符，关键文字带下划线 ═══
    authority = authority_content.get(data.entrustType)
    if authority is None:
        # 自定义类别没有预设文案；以类别名称作为文书中的代理阶段。
        with get_db() as conn:
            row = conn.execute(
                "SELECT label FROM power_attorney_custom_entrust_types WHERE id=?", (data.entrustType,)
            ).fetchone()
        authority = {'stage': row[0] if row else '其他', 'authorities': []}
    saved_authorities = None
    if data.authorityContent:
        saved_authorities = [item.strip() for item in data.authorityContent if item.strip()]
    else:
        with get_db() as conn:
            row = conn.execute(
                "SELECT authorities_json FROM power_attorney_authority_templates WHERE entrust_type=?",
                (data.entrustType,),
            ).fetchone()
        if row:
            try:
                saved_authorities = [str(item).strip() for item in json.loads(row[0] or "[]") if str(item).strip()]
            except (TypeError, ValueError, json.JSONDecodeError):
                saved_authorities = None
    if saved_authorities:
        authority = {**authority, 'authorities': saved_authorities}
    parties_text = '、'.join(data.parties) if data.parties else '对方当事人'
    # 代理阶段：优先使用用户填写的代理阶段（可多个），未填写时回退到委托类别默认阶段。
    stages_text = "、".join(s.strip() for s in (data.stages or []) if s.strip()) or authority['stage']

    # 构建案号部分 - 格式：【案号：XXXXX】，有输入才显示
    case_number_text = f"【案号：{data.caseNumber}】" if data.caseNumber else ""

    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    p.paragraph_format.line_spacing = Pt(25)
    p.paragraph_format.space_after = Pt(0)

    if data.entrustType == 'execApplicant':
        add_run_fs(p, "现授权上述受委托人在本委托人申请")
        add_run_fs(p, f"强制执行{parties_text}财产一案", underline=True)
        if case_number_text:
            add_run_fs(p, f" {case_number_text}", underline=True)
        add_run_fs(p, "中，作为我方")
        add_run_fs(p, stages_text, underline=True)
        add_run_fs(p, "的代理人。代理人的代理权限为")
        add_run_fs(p, "特别授权", underline=True)
        add_run_fs(p, "，具体如下：")
    elif data.entrustType == 'execRespondent':
        add_run_fs(p, "现授权上述受委托人在")
        add_run_fs(p, parties_text, underline=True)
        add_run_fs(p, "申请执行本委托人财产一案", underline=True)
        if case_number_text:
            add_run_fs(p, f" {case_number_text}", underline=True)
        add_run_fs(p, "中，作为我方")
        add_run_fs(p, stages_text, underline=True)
        add_run_fs(p, "阶段的代理人。代理人的代理权限为")
        add_run_fs(p, "特别授权", underline=True)
        add_run_fs(p, "，具体如下：")
    elif data.entrustType == 'bankruptcy':
        add_run_fs(p, "现授权上述受委托人在")
        add_run_fs(p, parties_text, underline=True)
        add_run_fs(p, f"的{data.caseType or '破产清算'}一案")
        if case_number_text:
            add_run_fs(p, f" {case_number_text}", underline=True)
        add_run_fs(p, "中，作为我方")
        add_run_fs(p, stages_text, underline=True)
        add_run_fs(p, "阶段的代理人。代理人的代理权限为")
        add_run_fs(p, "特别授权", underline=True)
        add_run_fs(p, "，具体如下：")
    elif data.entrustType == 'execObjection':
        add_run_fs(p, "现授权上述受委托人在本委托人与")
        add_run_fs(p, parties_text, underline=True)
        add_run_fs(p, "的执行异议一案", underline=True)
        if case_number_text:
            add_run_fs(p, f" {case_number_text}", underline=True)
        add_run_fs(p, "中，作为我方")
        add_run_fs(p, stages_text, underline=True)
        add_run_fs(p, "阶段的代理人。代理人的代理权限为")
        add_run_fs(p, "特别授权", underline=True)
        add_run_fs(p, "，具体如下：")
    else:
        case_type_text = document_cause_label(data.caseType, frontend_dir)
        add_run_fs(p, "现授权上述受委托人在本委托人与")
        add_run_fs(p, parties_text, underline=True)
        if case_type_text:
            add_run_fs(p, f"的{case_type_text}一案", underline=True)
        else:
            add_run_fs(p, "的纠纷一案", underline=True)
        if case_number_text:
            add_run_fs(p, f" {case_number_text}", underline=True)
        add_run_fs(p, "中，作为我方")
        add_run_fs(p, stages_text, underline=True)
        add_run_fs(p, "阶段的代理人。代理人的代理权限为")
        add_run_fs(p, "特别授权", underline=True)
        add_run_fs(p, "，具体如下：")

    # ═══ 权限列表 - 左缩进2字符，编号1-N ═══
    for i, auth in enumerate(authority['authorities'], 1):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.74)
        p.paragraph_format.line_spacing = Pt(25)
        p.paragraph_format.space_after = Pt(0)
        add_run_fs(p, f"{i}. {auth}")

    # 一个空行（落款前间距）
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = Pt(25)
    p.paragraph_format.space_after = Pt(0)

    # ═══ 签名区域 - 右对齐，仿宋字体 ═══
    date_str = ""
    try:
        date_obj = datetime.datetime.strptime(data.date, '%Y-%m-%d')
        date_str = f"{date_obj.year}年{date_obj.month}月{date_obj.day}日"
    except:
        date_str = data.date

    if is_legal:
        # 法人签名 - 右对齐，去掉下划线
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.line_spacing = Pt(25)
        p.paragraph_format.space_after = Pt(0)
        add_run_fs(p, "委托人：")
        add_run_fs(p, data.clientName)

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.line_spacing = Pt(25)
        p.paragraph_format.space_after = Pt(0)
        add_run_fs(p, "法定代表人：")
        add_run_fs(p, data.legalRepresentative or '')

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.line_spacing = Pt(25)
        p.paragraph_format.space_after = Pt(0)
        add_run_fs(p, date_str)
    else:
        # 自然人签名 - 右对齐，去掉下划线
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.line_spacing = Pt(25)
        p.paragraph_format.space_after = Pt(0)
        add_run_fs(p, "委托人：")
        add_run_fs(p, data.clientName)

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.line_spacing = Pt(25)
        p.paragraph_format.space_after = Pt(0)
        add_run_fs(p, date_str)

    # 保存到内存
    from io import BytesIO
    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return output.getvalue()


def generate_rep_identity_cert_docx(data: RepIdentityCertRequest) -> bytes:
    """生成法定代表人身份证明书 Word 文档 - 严格按照模板格式"""
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    def add_run(p, text, size=14, font='仿宋', bold=False, underline=False):
        """添加一个run"""
        run = p.add_run(text)
        run.font.size = Pt(size)
        run.font.name = font
        run._element.rPr.rFonts.set(qn('w:eastAsia'), font)
        run.bold = bold
        if underline:
            run.underline = True
        return run

    def set_paragraph_spacing(para, before=0, after=0, line_spacing=1.5):
        """设置段落间距"""
        para.paragraph_format.space_before = Pt(before)
        para.paragraph_format.space_after = Pt(after)
        para.paragraph_format.line_spacing = line_spacing

    def set_first_line_indent(para, indent):
        """设置首行缩进"""
        para.paragraph_format.first_line_indent = indent

    doc = Document()

    # 设置页面尺寸（A4）和边距
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.17)
    section.right_margin = Cm(3.17)

    # 标题上方空行
    doc.add_paragraph()

    # 标题 - 二号黑体加粗居中 (22pt)
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_run(title_para, '法定代表人身份证明书', size=22, font='黑体', bold=True)
    set_paragraph_spacing(title_para, before=0, after=12, line_spacing=2.0)

    # 标题下方空行
    doc.add_paragraph()

    # 兹证明行 - 首行缩进两个字
    para1 = doc.add_paragraph()
    set_first_line_indent(para1, Cm(0.74))  # 首行缩进2个字
    add_run(para1, '兹证明', size=14, font='仿宋')
    # 法定代表人加粗+下划线
    add_run(para1, data.repName, size=14, font='仿宋', bold=True, underline=True)
    add_run(para1, '是我公司的法定代表人，在我公司担任', size=14, font='仿宋')
    # 职务加粗+下划线（不换行，直接接在"在我公司担任"后面）
    add_run(para1, data.repTitle, size=14, font='仿宋', bold=True, underline=True)
    add_run(para1, '，特此证明！', size=14, font='仿宋')
    set_paragraph_spacing(para1, before=0, after=0, line_spacing=2.0)

    # 空行
    doc.add_paragraph()
    doc.add_paragraph()

    # 单位（盖章）- 右对齐
    para3 = doc.add_paragraph()
    para3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    add_run(para3, f'单位（盖章）：{data.clientName}', size=14, font='仿宋')
    set_paragraph_spacing(para3, before=0, after=12, line_spacing=2.0)

    # 日期 - 右对齐，格式：年  月  日
    para4 = doc.add_paragraph()
    para4.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    date_str = data.date
    if date_str:
        try:
            date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
            date_str = f'{date.year}年  {date.month}月  {date.day}日'
        except:
            date_str = data.date
    add_run(para4, date_str, size=14, font='仿宋')
    set_paragraph_spacing(para4, before=0, after=0, line_spacing=2.0)

    # 保存到内存
    from io import BytesIO
    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return output.getvalue()
