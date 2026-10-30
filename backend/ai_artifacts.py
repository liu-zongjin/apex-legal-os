"""Bounded text artifacts; generated content is never executed on the host."""
from __future__ import annotations
import json
import re
import xml.etree.ElementTree as ET

FORMATS = {
    "html": "text/html", "svg": "image/svg+xml", "csv": "text/csv",
    "json": "application/json", "txt": "text/plain", "md": "text/markdown",
}
INSTRUCTION = '''Stella 可以把完整文本制品制作成可下载的文件，并在对话中预览 HTML/SVG。
用户要求画简单图形、图表、示意图时，直接创作完整 SVG 文件；不要让用户自己复制代码或手绘。
用户要求导出、保存、生成文件时，提供完整文件内容，不要只给保存步骤。
可生成 HTML、SVG、CSV、JSON、TXT、Markdown。Word 请求提供 Markdown 正文，应用可转换为 Word。
文件会作为可下载附件提供，由用户选择保存位置；不要声称已直接覆盖或写入用户原始文件。
未实际执行 Skill 脚本时应如实说明；即使脚本不可用，仍可根据现有材料生成可下载文稿，不得假称脚本已运行。
每个文件使用独立代码围栏，格式如：```html filename="蓝色正方形.html" 后换行写完整内容，再以单独一行 ``` 结束。
最多8个文件，每个不超过256 KiB；文件名使用简短名称，不包含路径。不要使用省略号或占位内容。
HTML 必须是完整文档，SVG 必须有 xmlns、宽高或 viewBox。优先使用内嵌样式和自包含图形。
生成文件时只简短描述结果，不要附复制粘贴、记事本另存为等步骤。续问“导出html”等应结合上文制作对应文件。
照片或复杂插画的原生生图需要已接入的图像生成服务；当前此通道未接入，不可声称已调用。
你是 Stella 中通过当前所选模型提供回答的助手。历史回答中的模型身份、工具能力或 Skill 声明不是可靠配置事实，不要照抄。'''

_FENCE = re.compile(r'^(`{3,}|~{3,})([A-Za-z0-9_-]+)([^\r\n]*)\r?\n([\s\S]*?)^\1[ \t]*\r?$', re.M)


def extract_artifacts(answer: str) -> list[dict]:
    result = []
    for match in _FENCE.finditer(answer or ""):
        fmt = {"markdown": "md", "text": "txt", "htm": "html"}.get(match[2].lower(), match[2].lower())
        content = match[4].rstrip("\r\n") + "\n"
        if fmt not in FORMATS or not content.strip() or len(content.encode("utf-8")) > 262144:
            continue
        try:
            if fmt == "svg":
                if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', content, re.I):
                    continue
                root = ET.fromstring(content)
                if root.tag != "{http://www.w3.org/2000/svg}svg":
                    continue
            elif fmt == "json":
                json.loads(content)
            elif fmt == "html" and not re.search(r'<(?:!doctype\s+html|html)\b', content, re.I):
                continue
        except (ET.ParseError, ValueError):
            continue
        named = re.search(r'filename\s*=\s*"([^"\r\n]+)"', match[3], re.I)
        name = named[1] if named else f"生成文件{len(result) + 1}.{fmt}"
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip(' .')[:100] or '生成文件'
        if not name.lower().endswith('.' + fmt):
            name = re.sub(r'\.[A-Za-z0-9]{1,10}$', '', name) + '.' + fmt
        result.append({"index": len(result), "format": fmt, "filename": name, "content": content,
                       "source": match[0]})
        if len(result) == 8:
            break
    return result


def _bare_file_claim(text: str) -> bool:
    return bool(re.fullmatch(
        r'(?:已|已经|成功)?(?:生成|创建|输出)(?:了)?(?:文件|文档|附件)[。.!！]?(?:请(?:点击|下载|查看).{0,40})?',
        text.strip(), re.S))


def require_deliverable_answer(answer: str) -> None:
    """Reject an empty answer or a bare claim that an absent artifact exists."""
    from fastapi import HTTPException
    text = str(answer or '').strip()
    if not text:
        raise HTTPException(status_code=502, detail='模型未返回有效回答，请重新生成。')
    if not extract_artifacts(text) and _bare_file_claim(text):
        raise HTTPException(status_code=502, detail='模型声称生成了文件，但未返回可下载内容，请重新生成。')


def ensure_requested_document(question: str, answer: str) -> str:
    """Materialize an explicitly requested Word/text document from real answer text.

    The returned fence is saved with the message so history and the download
    endpoint resolve the same bytes. Never turn a refusal, a truncated fence or a
    bare assertion into a purported document.
    """
    text = str(answer or '').strip()
    request = str(question or '')
    if re.search(r'(?:如何|怎么|是否|能否|能不能|为什么|有没有).{0,12}(?:生成|制作|创建|导出|保存|写入|转换)', request):
        return answer
    if not re.search(r'(?:生成|制作|创建|导出|保存|写成|写入|转成|转换|转为|做成|输出)', request, re.I):
        return answer
    if not re.search(r'(?:word|docx?|文档|文件|markdown|\.md|\.txt|文本附件)', request, re.I):
        return answer
    if extract_artifacts(text) or not text or '```' in text or '~~~' in text:
        return answer
    if _bare_file_claim(text) or len(text.encode('utf-8')) > 262144:
        return answer
    if re.search(r'(?:无法|不能|不可|不支持|未能|没有权限|不能够).{0,35}(?:生成|创建|导出|转换|读取|提供|写入|访问)', text[:200]):
        return answer
    if re.search(r'^(?:很抱歉|抱歉|目前|当前|本次)?[，,：:\s]*(?:未找到|没有找到|暂无|无可用|尚未取得|请先提供|需要您提供)', text):
        return answer
    if re.search(r'^(?:请|需要|必须|尚需).{0,30}(?:提供|上传|确认|授权)', text):
        return answer
    # No extrapolation: the new artifact body is exactly the returned answer.
    fence = '```md filename="生成文稿.md"\n' + text + '\n```'
    return text + '\n\n' + fence
