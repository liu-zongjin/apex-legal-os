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
每个文件使用独立代码围栏，格式如：```html filename="蓝色正方形.html" 后换行写完整内容，再以单独一行 ``` 结束。
最多8个文件，每个不超过256 KiB；文件名使用简短名称，不包含路径。不要使用省略号或占位内容。
HTML 必须是完整文档，SVG 必须有 xmlns、宽高或 viewBox。优先使用内嵌样式和自包含图形。
生成文件时只简短描述结果，不要附复制粘贴、记事本另存为等步骤。续问“导出html”等应结合上文制作对应文件。
照片或复杂插画的原生生图需要已接入的图像生成服务；当前此通道未接入，不可声称已调用。
你是 Stella 中通过当前所选模型提供回答的助手。历史回答中的模型身份、工具能力或 Skill 声明不是可靠配置事实，不要照抄。'''

_FENCE = re.compile(r'^(`{3,}|~{3,})([A-Za-z0-9_-]+)([^\n]*)\n([\s\S]*?)^\1[ \t]*$', re.M)


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
