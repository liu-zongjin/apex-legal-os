"""本地法院通讯录：公开来源与案件资料统一留痕、审核后入库。"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .ai_client import call_ai_with_fallback
from .ai_config import DEFAULT_AI_MODEL


PROVINCES = [
    ("北京市", "直辖市"), ("天津市", "直辖市"), ("河北省", "省"), ("山西省", "省"),
    ("内蒙古自治区", "自治区"), ("辽宁省", "省"), ("吉林省", "省"), ("黑龙江省", "省"),
    ("上海市", "直辖市"), ("江苏省", "省"), ("浙江省", "省"), ("安徽省", "省"),
    ("福建省", "省"), ("江西省", "省"), ("山东省", "省"), ("河南省", "省"),
    ("湖北省", "省"), ("湖南省", "省"), ("广东省", "省"), ("广西壮族自治区", "自治区"),
    ("海南省", "省"), ("重庆市", "直辖市"), ("四川省", "省"), ("贵州省", "省"),
    ("云南省", "省"), ("西藏自治区", "自治区"), ("陕西省", "省"), ("甘肃省", "省"),
    ("青海省", "省"), ("宁夏回族自治区", "自治区"), ("新疆维吾尔自治区", "自治区"),
]
GUANGDONG_COURTS = [
    ("广州市中级人民法院", "广州市", "中级"), ("深圳市中级人民法院", "深圳市", "中级"),
    ("珠海市中级人民法院", "珠海市", "中级"), ("汕头市中级人民法院", "汕头市", "中级"),
    ("佛山市中级人民法院", "佛山市", "中级"), ("韶关市中级人民法院", "韶关市", "中级"),
    ("河源市中级人民法院", "河源市", "中级"), ("梅州市中级人民法院", "梅州市", "中级"),
    ("惠州市中级人民法院", "惠州市", "中级"), ("汕尾市中级人民法院", "汕尾市", "中级"),
    ("东莞市中级人民法院", "东莞市", "中级"), ("中山市中级人民法院", "中山市", "中级"),
    ("江门市中级人民法院", "江门市", "中级"), ("阳江市中级人民法院", "阳江市", "中级"),
    ("湛江市中级人民法院", "湛江市", "中级"), ("茂名市中级人民法院", "茂名市", "中级"),
    ("肇庆市中级人民法院", "肇庆市", "中级"), ("清远市中级人民法院", "清远市", "中级"),
    ("潮州市中级人民法院", "潮州市", "中级"), ("揭阳市中级人民法院", "揭阳市", "中级"),
    ("云浮市中级人民法院", "云浮市", "中级"), ("广州互联网法院", "广州市", "专门"),
    ("广州知识产权法院", "广州市", "专门"), ("广州铁路运输中级法院", "广州市", "专门"),
    ("广东自由贸易区南沙片区人民法院", "广州市", "基层"),
]
GUANGDONG_BASIC = [
    "广州市越秀区人民法院", "广州市荔湾区人民法院", "广州市海珠区人民法院", "广州市天河区人民法院", "广州市白云区人民法院", "广州市黄埔区人民法院", "广州市番禺区人民法院", "广州市花都区人民法院", "广州市南沙区人民法院", "广州市从化区人民法院", "广州市增城区人民法院",
    "深圳市福田区人民法院", "深圳市罗湖区人民法院", "深圳市南山区人民法院", "深圳市盐田区人民法院", "深圳市宝安区人民法院", "深圳市龙岗区人民法院", "深圳市龙华区人民法院", "深圳市坪山区人民法院", "深圳市光明区人民法院", "深圳前海合作区人民法院",
    "佛山市禅城区人民法院", "佛山市南海区人民法院", "佛山市顺德区人民法院", "佛山市三水区人民法院", "佛山市高明区人民法院", "东莞市第一人民法院", "东莞市第二人民法院", "东莞市第三人民法院", "中山市第一人民法院", "中山市第二人民法院",
]
DEPT_ALIASES = {"民一庭": "民事审判第一庭", "民二庭": "民事审判第二庭", "民三庭": "民事审判第三庭", "民四庭": "民事审判第四庭", "民五庭": "民事审判第五庭", "民六庭": "民事审判第六庭", "刑庭": "刑事审判庭", "刑一庭": "刑事审判第一庭", "刑二庭": "刑事审判第二庭", "行政庭": "行政审判庭", "审管办": "审判管理办公室", "法警队": "司法警察大队", "执行局": "执行局", "立案庭": "立案庭"}
PHONE_RE = re.compile(r"(?<!\d)(?:0\d{2,3}[-— ]?)?[2-9]\d{6,7}(?!\d)|1[3-9]\d{9}(?!\d)")
HOTLINE_RE = re.compile(r"(?<!\d)1\d{4}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
NAME_RE = re.compile(r"(?:法官|法官助理|书记员|承办人|审判员)\s*[：:]?\s*([\u4e00-\u9fff]{2,4})|([\u4e00-\u9fff]{2,4})\s*(?:法官|法官助理|书记员|审判员)")
NON_PERSON_NAMES = {"一审", "二审", "再审", "执行", "民事", "刑事", "法院", "人民", "本院", "案件", "审判", "庭审", "联系", "电话", "书记员", "法官助理", "承办人", "保安", "保安室", "总机", "传真", "值班", "信访", "立案", "送达"}


def _enhance_ocr_image(img: Image.Image) -> Optional[Image.Image]:
    """对表格型照片做去表格线、去噪、放大与 Otsu 二值化增强；非表格或无有效增强时返回 None。

    先精确检测并抹除横竖长表格线（仅线像素，不误伤文字），再做去噪与 Otsu 二值化，
    使 Tesseract 能以“姓名 + 电话”同行方式识别通讯录表格。
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except Exception:
        return None
    arr = np.array(img.convert("L"))
    if max(arr.shape) > 2400:
        f = 2400 / max(arr.shape)
        big = cv2.resize(arr, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    else:
        big = arr.copy()
    dn = cv2.fastNlMeansDenoising(big, None, 7, 7, 21)
    bw = cv2.adaptiveThreshold(dn, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8)
    h, w = bw.shape
    kh = max(6, int(w * 0.06))
    kv = max(6, int(h * 0.14))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kh, 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, kv)))
    line = cv2.add(horiz, vert)
    if not line.any():
        return None
    clean = dn.copy().astype(np.int16)
    clean[line > 0] = 255
    clean = clean.astype(np.uint8)
    _, otsu = cv2.threshold(clean, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(otsu)


def _vision_ocr_image(data: bytes) -> str:
    """优先调用 macOS Vision 的本地中文 OCR，并按版面坐标还原表格行。

    Apple Vision 对拍照件的中文印刷体、反光和轻微透视比 Tesseract 稳定得多；
    所有处理仍在本机完成。非 macOS 或 Vision 不可用时返回空串，由 Tesseract 兜底。
    """
    helper = Path(__file__).with_name("court_directory_vision_ocr.swift")
    if not helper.is_file() or not shutil.which("swift"):
        return ""
    try:
        run = subprocess.run(
            ["swift", str(helper)], input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=20, check=True,
        )
        payload = json.loads(run.stdout.decode("utf-8"))
        items = payload.get("items", []) if isinstance(payload, dict) else []
    except Exception:
        return ""
    cells = []
    for item in items:
        try:
            text = str(item.get("text") or "").strip()
            x, y, height = float(item["x"]), float(item["y"]), float(item["height"])
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if text:
            cells.append((y, x, max(height, 0.001), text))
    if not cells:
        return ""
    # Vision 将同一表格行的三个单元格分别返回，且拍照透视会让右侧单元格的 y
    # 坐标明显低于左侧。检测到“姓名”列时，改由第一列锚定一行并吸收下一姓名
    # 前的号码单元格，避免姓名和上一/下一行电话串在一起。
    anchors = [cell for cell in sorted(cells) if cell[1] < 0.42]
    is_table = any(cell[3] == "姓名" for cell in anchors) and len(anchors) >= 4
    if is_table:
        lines = []
        first_anchor_y = anchors[0][0]
        for cell in sorted((value for value in cells if value[0] < first_anchor_y - 0.001), key=lambda value: (value[0], value[1])):
            lines.append([cell])
        for index, anchor in enumerate(anchors):
            next_y = anchors[index + 1][0] if index + 1 < len(anchors) else float("inf")
            row = [cell for cell in cells if anchor[0] - 0.001 <= cell[0] < next_y]
            lines.append(row)
    else:
        lines = []
        for cell in sorted(cells, key=lambda value: (value[0], value[1])):
            if lines:
                previous = lines[-1]
                average_y = sum(value[0] for value in previous) / len(previous)
                tolerance = max(0.012, max(cell[2], *(value[2] for value in previous)) * 0.8)
                if abs(cell[0] - average_y) <= tolerance:
                    previous.append(cell)
                    continue
            lines.append([cell])
    return "\n".join(" | ".join(value[3] for value in sorted(line, key=lambda value: value[1])) for line in lines)


def ocr_image_bytes(data: bytes) -> str:
    """本机 Tesseract OCR（与“开庭提醒-上传截图识别”同方案，不联网、不收费）。

    对表格型通讯录照片自动去表格线、放大、去噪与 Otsu 二值化增强，再以
    psm 6 / psm 4 双模式识别拼接收敛结果；无 OpenCV 时回退为对比度增强直识别。
    """
    vision_text = _vision_ocr_image(data)
    if len(re.findall(PHONE_RE.pattern, vision_text)) >= 3:
        return vision_text
    try:
        from PIL import Image, ImageOps
        import pytesseract
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"本机 OCR 依赖不可用：{exc}")
    if not os.path.isabs(getattr(pytesseract.pytesseract, "tesseract_cmd", "") or ""):
        detected = shutil.which("tesseract") or next((c for c in ("/usr/local/bin/tesseract", "/opt/homebrew/bin/tesseract", "/usr/bin/tesseract") if os.path.isfile(c)), "")
        if detected:
            pytesseract.pytesseract.tesseract_cmd = detected
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("L")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"图片无法解析：{exc}")
    candidates: list[Image.Image] = []
    enhanced = _enhance_ocr_image(img)
    if enhanced is not None:
        candidates.append(enhanced)
    else:
        candidates.append(ImageOps.autocontrast(img))
    texts: list[str] = []
    for candidate in candidates:
        candidate_texts: list[str] = []
        for config in ("--psm 6", "--psm 4"):
            try:
                text = pytesseract.image_to_string(candidate, lang="chi_sim", config=config)
            except Exception:
                continue
            if text.strip():
                candidate_texts.append(text)
        # 表格型通讯录用纯 chi_sim，让“姓名 + 电话”尽量落在同一行、姓名更准确；
        # psm 4 在 psm 6 未识别出电话时兜底。
        if candidate_texts and len(re.findall(PHONE_RE.pattern, candidate_texts[0])) >= 1:
            texts.append(candidate_texts[0])
        elif candidate_texts:
            texts.append("".join(candidate_texts))
    return "\n".join(texts)


def _ocr_phone_leniency(text: str) -> str:
    """修正本机 OCR 对数字的常见误读，提高电话识别率。

    竖线（| ｜）是表格列分隔符或 OCR 残影，不转成数字，交由后续姓名/字段清洗剥离。
    """
    if not text:
        return text
    fixed = []
    for ch in text:
        if ch in "oO":
            fixed.append("0")
        elif ch in "lI":
            fixed.append("1")
        elif ch in "cC":
            fixed.append("0")
        elif ch in "sS":
            fixed.append("5")
        elif ch in "zZ":
            fixed.append("2")
        elif ch in "bB":
            fixed.append("8")
        elif ch in "gG":
            fixed.append("9")
        elif ch in "qQ":
            fixed.append("9")
        else:
            fixed.append(ch)
    return "".join(fixed)


def register_court_directory_routes(app: Any, get_db: Callable[[], Any], frontend_dir: Path, weixin_fetcher: Optional[Callable[[str], Any]] = None) -> None:
    def now() -> str:
        return dt.datetime.now().isoformat(timespec="seconds")

    def norm(value: Any) -> str:
        return re.sub(r"\s+", "", str(value or "")).strip()

    def canonical_department(value: Any) -> str:
        text = norm(value)
        # 去掉“政治部(机关党委)”“立案庭（诉讼服务中心）”等括号说明，归并到主体部门。
        m = re.match(r"^([\u4e00-\u9fff]{2,12})[（(]", text)
        if m:
            text = m.group(1)
        return DEPT_ALIASES.get(text, text)

    def normalized_phone(value: Any) -> str:
        return re.sub(r"[^0-9]", "", str(value or ""))

    def valid_phone(value: Any) -> bool:
        digits = normalized_phone(value)
        # 全国法院诉讼服务热线。它是有效的五位号码，不应被通用座机规则过滤。
        if digits == "12368":
            return True
        # 8 位日期（例如 20240603）不能误识别成座机分机。
        if re.fullmatch(r"20\d{6}", digits):
            return False
        if re.fullmatch(r"1[3-9]\d{9}", digits):
            return True
        if re.fullmatch(r"0\d{9,11}", digits):
            return True
        return bool(re.fullmatch(r"[2-9]\d{6,7}", digits))

    def normalize_published(value: Any) -> str:
        """把各种发布时间写法统一成 ISO 格式（2026-07-31T08:00:00）。"""
        text = norm(value)
        if not text:
            return ""
        m = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", text)
        if not m:
            return text[:60]
        date_part = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        t = re.search(r"(\d{1,2})[:：](\d{2})", text)
        time_part = f"T{int(t.group(1)):02d}:{t.group(2)}:00" if t else "T00:00:00"
        return date_part + time_part

    def extract_publish_time(soup: Any, weixin_time: str = "") -> str:
        """从页面元数据或显式时间节点中提取公开来源的发布时间。"""
        if weixin_time:
            return normalize_published(weixin_time)
        for attrs in ({"property": "article:published_time"}, {"name": "article:published_time"},
                      {"property": "og:article:published_time"}, {"name": "og:article:published_time"},
                      {"property": "og:release_date"}, {"name": "parsely-pub-date"}, {"name": "publish_date"},
                      {"name": "date"}, {"itemprop": "datePublished"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content") and re.search(r"\d{4}", str(tag["content"])):
                return normalize_published(tag["content"])
        node = soup.find(id="publish_time") or soup.find("time")
        if not node:
            node = soup.find(attrs={"class": re.compile(r"publish[_ ]?time|entry[_ -]?date|post[_ -]?date", re.I)})
        if node:
            text = norm(node.get_text(" ", strip=True))
            if re.search(r"\d{4}", text):
                return normalize_published(text)
        return ""

    def ensure_schema() -> None:
        with get_db() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS court_directory_courts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE,
              court_level TEXT NOT NULL DEFAULT '', province TEXT DEFAULT '', city TEXT DEFAULT '', is_phase_one INTEGER DEFAULT 0,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(parent_id) REFERENCES court_directory_courts(id));
            CREATE INDEX IF NOT EXISTS idx_court_directory_courts_parent ON court_directory_courts(parent_id);
            CREATE TABLE IF NOT EXISTS court_directory_departments (
              id INTEGER PRIMARY KEY AUTOINCREMENT, court_id INTEGER NOT NULL, name TEXT NOT NULL, normalized_name TEXT NOT NULL,
              aliases_json TEXT DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(court_id, normalized_name), FOREIGN KEY(court_id) REFERENCES court_directory_courts(id));
            CREATE TABLE IF NOT EXISTS court_directory_people (
              id INTEGER PRIMARY KEY AUTOINCREMENT, court_id INTEGER NOT NULL, name TEXT NOT NULL, normalized_name TEXT NOT NULL,
              manual_status TEXT DEFAULT '', status_note TEXT DEFAULT '', status_at TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(court_id, normalized_name), FOREIGN KEY(court_id) REFERENCES court_directory_courts(id));
            CREATE TABLE IF NOT EXISTS court_directory_affiliations (
              id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER NOT NULL, department_id INTEGER, position TEXT DEFAULT '',
              status TEXT DEFAULT 'unknown', effective_at TEXT DEFAULT '', ended_at TEXT DEFAULT '', source_id INTEGER, created_at TEXT NOT NULL,
              UNIQUE(person_id, department_id, position, source_id));
            CREATE TABLE IF NOT EXISTS court_directory_sources (
              id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT NOT NULL, source_url TEXT DEFAULT '', title TEXT DEFAULT '', raw_text TEXT DEFAULT '',
              published_at TEXT DEFAULT '', collected_at TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE, case_id INTEGER, case_title TEXT DEFAULT '', case_number TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS court_directory_contacts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, owner_kind TEXT NOT NULL, owner_id INTEGER NOT NULL, phone TEXT NOT NULL, normalized_phone TEXT NOT NULL,
              email TEXT DEFAULT '', manual_status TEXT DEFAULT '', status_note TEXT DEFAULT '', status_at TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(owner_kind, owner_id, normalized_phone));
            CREATE TABLE IF NOT EXISTS court_directory_contact_observations (
              id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER NOT NULL, source_id INTEGER NOT NULL, observed_at TEXT DEFAULT '', evidence TEXT DEFAULT '', created_at TEXT NOT NULL,
              UNIQUE(contact_id, source_id), FOREIGN KEY(contact_id) REFERENCES court_directory_contacts(id), FOREIGN KEY(source_id) REFERENCES court_directory_sources(id));
            CREATE TABLE IF NOT EXISTS court_directory_import_batches (
              id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, title TEXT DEFAULT '', raw_text TEXT DEFAULT '', published_at TEXT DEFAULT '',
              status TEXT NOT NULL DEFAULT 'preview', extraction_json TEXT DEFAULT '[]', created_at TEXT NOT NULL, confirmed_at TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS court_directory_audit_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, target_kind TEXT NOT NULL, target_id INTEGER NOT NULL, action TEXT NOT NULL, detail_json TEXT DEFAULT '{}', created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_court_directory_people_court_name ON court_directory_people(court_id, normalized_name);
            CREATE INDEX IF NOT EXISTS idx_court_directory_contacts_owner ON court_directory_contacts(owner_kind, owner_id);
            """)
            # 清理早期版本因 department_id 为 NULL 而重复累积的任职记录（UNIQUE 约束对 NULL 不生效）。
            try:
                conn.execute("DELETE FROM court_directory_affiliations WHERE id NOT IN (SELECT MIN(id) FROM court_directory_affiliations GROUP BY person_id, COALESCE(department_id,-1), position, COALESCE(source_id,-1))")
            except Exception:
                pass
            # 兼容早期库：为 contacts 补充 email 列。
            try:
                if "email" not in {r["name"] for r in conn.execute("PRAGMA table_info(court_directory_contacts)").fetchall()}:
                    conn.execute("ALTER TABLE court_directory_contacts ADD COLUMN email TEXT DEFAULT ''")
            except Exception:
                pass
            seed_courts(conn)
            conn.commit()

    def court_id(conn: Any, name: str, create: bool = False) -> int | None:
        value = norm(name)
        if not value:
            return None
        row = conn.execute("SELECT id FROM court_directory_courts WHERE normalized_name=?", (value,)).fetchone()
        if row:
            return int(row[0])
        if not create:
            # 公开资料常省略城市前缀，例如“南山区人民法院”。仅在唯一命中既有法院时归入，
            # 绝不据此新增或跨法院合并。
            candidates = conn.execute("SELECT id FROM court_directory_courts WHERE normalized_name LIKE ?", (f"%{value}",)).fetchall()
            if len(candidates) == 1:
                return int(candidates[0][0])
            return None
        stamp = now()
        # 按省份（含直辖市）找对应高级人民法院作为父级；无法识别省份时挂顶层。
        province = next((p for p, _ in PROVINCES if p in value), "")
        parent = None
        if province:
            parent = conn.execute("SELECT id FROM court_directory_courts WHERE normalized_name=? AND court_level='高级'", (f"{province}高级人民法院",)).fetchone()
        cur = conn.execute("INSERT INTO court_directory_courts(parent_id,name,normalized_name,court_level,province,is_phase_one,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (int(parent[0]) if parent else None, value, value, "基层", province, 1, stamp, stamp))
        return int(cur.lastrowid)

    def insert_court(conn: Any, name: str, parent_id: int | None, level: str, province: str = "", city: str = "", phase: int = 0) -> int:
        stamp = now()
        conn.execute("INSERT OR IGNORE INTO court_directory_courts(parent_id,name,normalized_name,court_level,province,city,is_phase_one,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (parent_id, name, norm(name), level, province, city, phase, stamp, stamp))
        return int(conn.execute("SELECT id FROM court_directory_courts WHERE normalized_name=?", (norm(name),)).fetchone()[0])

    def seed_courts(conn: Any) -> None:
        supreme = insert_court(conn, "最高人民法院", None, "最高")
        circuit_group = insert_court(conn, "巡回法庭", supreme, "分组")
        for idx in range(1, 7):
            insert_court(conn, f"最高人民法院第{idx}巡回法庭", circuit_group, "巡回法庭")
        # 兼容早期版本：把曾直接挂在最高院下的六个巡回法庭归入统一折叠组。
        conn.execute("UPDATE court_directory_courts SET parent_id=? WHERE name GLOB '最高人民法院第*巡回法庭'", (circuit_group,))
        for province, kind in PROVINCES:
            high_name = f"{province}高级人民法院" if kind != "直辖市" else f"{province}高级人民法院"
            high = insert_court(conn, high_name, supreme, "高级", province)
            if province == "广东省":
                for name, city, level in GUANGDONG_COURTS:
                    insert_court(conn, name, high, level, province, city, 1)
                for name in GUANGDONG_BASIC:
                    city = next((c for c in ("广州市", "深圳市", "佛山市", "东莞市", "中山市") if c[:2] in name), "")
                    insert_court(conn, name, high, "基层", province, city, 1)
        rebuild_hierarchy(conn)

    def rebuild_hierarchy(conn: Any) -> None:
        """把广东节点修正为 高院 → 中院 → 基层院，兼容早期扁平初始化的数据。"""
        high = conn.execute("SELECT id FROM court_directory_courts WHERE normalized_name='广东省高级人民法院'").fetchone()
        if not high:
            return
        high_id = int(high[0])
        rows = conn.execute("SELECT id,name,city,court_level FROM court_directory_courts WHERE province='广东省'").fetchall()
        intermediate_by_city = {}
        for row in rows:
            if row["court_level"] == "中级":
                intermediate_by_city[norm(row["city"])] = int(row["id"])
                conn.execute("UPDATE court_directory_courts SET parent_id=? WHERE id=?", (high_id, row["id"]))
        # 广州互联网法院、广州知识产权法院归入广州市中级人民法院下级。
        gz_mid = conn.execute("SELECT id FROM court_directory_courts WHERE normalized_name='广州市中级人民法院'").fetchone()
        if gz_mid:
            for name in ("广州互联网法院", "广州知识产权法院"):
                conn.execute("UPDATE court_directory_courts SET parent_id=? WHERE normalized_name=?", (gz_mid[0], name))
        for row in rows:
            if row["court_level"] != "基层":
                continue
            city = norm(row["city"])
            parent_id = intermediate_by_city.get(city)
            if not parent_id:
                parent_id = next((value for key, value in intermediate_by_city.items() if key and (key[:2] in norm(row["name"]) or key in norm(row["name"]))), None)
            if parent_id:
                conn.execute("UPDATE court_directory_courts SET parent_id=? WHERE id=?", (parent_id, row["id"]))

    def source_upsert(conn: Any, kind: str, url: str, title: str, raw: str, published_at: str = "", case_id: int | None = None, case_title: str = "", case_number: str = "") -> int:
        fingerprint = hashlib.sha256(f"{kind}|{url}|{raw}".encode()).hexdigest()
        row = conn.execute("SELECT id FROM court_directory_sources WHERE fingerprint=?", (fingerprint,)).fetchone()
        if row:
            return int(row[0])
        cur = conn.execute("INSERT INTO court_directory_sources(source_kind,source_url,title,raw_text,published_at,collected_at,fingerprint,case_id,case_title,case_number) VALUES(?,?,?,?,?,?,?,?,?,?)", (kind, url, title[:300], raw[:120000], published_at, now(), fingerprint, case_id, case_title[:300], case_number[:200]))
        return int(cur.lastrowid)

    def upsert_entry(conn: Any, source_id: int, entry: dict[str, Any]) -> dict[str, Any]:
        court_name, name = norm(entry.get("court")), norm(entry.get("name"))
        dept_name, position = canonical_department(entry.get("department")), norm(entry.get("position"))
        phone, observed = norm(entry.get("phone")), norm(entry.get("observed_at"))
        email = norm(entry.get("email"))[:120]
        # 法院树是受控主数据；自由文本只能匹配既有法院，绝不据此反向创建节点。
        cid = court_id(conn, court_name, create=False)
        if not cid or not valid_phone(phone) or not re.search(r"(人民法院|法院|中院|法庭)$", court_name):
            return {"ok": False, "reason": "缺少可识别法院或联系电话"}
        did = None
        if dept_name:
            stamp = now()
            conn.execute("INSERT OR IGNORE INTO court_directory_departments(court_id,name,normalized_name,aliases_json,created_at,updated_at) VALUES(?,?,?,?,?,?)", (cid, dept_name, dept_name, json.dumps([k for k, v in DEPT_ALIASES.items() if v == dept_name], ensure_ascii=False), stamp, stamp))
            did = int(conn.execute("SELECT id FROM court_directory_departments WHERE court_id=? AND normalized_name=?", (cid, dept_name)).fetchone()[0])
        owner_kind, owner_id = "department", did
        person_id = None
        if name:
            stamp = now()
            conn.execute("INSERT OR IGNORE INTO court_directory_people(court_id,name,normalized_name,created_at,updated_at) VALUES(?,?,?,?,?)", (cid, name, name, stamp, stamp))
            person_id = int(conn.execute("SELECT id FROM court_directory_people WHERE court_id=? AND normalized_name=?", (cid, name)).fetchone()[0])
            aff_exists = conn.execute("SELECT id FROM court_directory_affiliations WHERE person_id=? AND COALESCE(department_id,-1)=? AND position=? AND COALESCE(source_id,-1)=?", (person_id, did if did is not None else -1, position, source_id if source_id is not None else -1)).fetchone()
            if not aff_exists:
                conn.execute("INSERT INTO court_directory_affiliations(person_id,department_id,position,status,effective_at,source_id,created_at) VALUES(?,?,?,?,?,?,?)", (person_id, did, position, "unknown", observed, source_id, stamp))
            owner_kind, owner_id = "person", person_id
        if not owner_id:
            return {"ok": False, "reason": "缺少人员或部门"}
        clean_phone, stamp = normalized_phone(phone), now()
        conn.execute("INSERT OR IGNORE INTO court_directory_contacts(owner_kind,owner_id,phone,normalized_phone,email,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (owner_kind, owner_id, phone, clean_phone, email, stamp, stamp))
        contact_id = int(conn.execute("SELECT id FROM court_directory_contacts WHERE owner_kind=? AND owner_id=? AND normalized_phone=?", (owner_kind, owner_id, clean_phone)).fetchone()[0])
        if email:
            conn.execute("UPDATE court_directory_contacts SET email=? WHERE id=? AND COALESCE(email,'')=''", (email, contact_id))
        conn.execute("INSERT OR IGNORE INTO court_directory_contact_observations(contact_id,source_id,observed_at,evidence,created_at) VALUES(?,?,?,?,?)", (contact_id, source_id, observed, norm(entry.get("evidence"))[:800], stamp))
        return {"ok": True, "court_id": cid, "person_id": person_id, "department_id": did, "contact_id": contact_id}

    def detect_court_names(text: str) -> list[str]:
        """从正文中检测法院全称（如“北京市朝阳区人民法院”），按出现顺序去重返回。"""
        names: list[str] = []
        for m in re.finditer(r"[\u4e00-\u9fff]{2,10}人民法院", text or ""):
            name = m.group(0)
            if name not in names:
                names.append(name)
        if not names:
            for m in re.finditer(r"[\u4e00-\u9fff]{2,8}法院(?!电话|通讯录|联系|办公|地址|诉讼|接待)", text or ""):
                name = m.group(0)
                if name not in names:
                    names.append(name)
        return names

    def split_court_segments(conn: Any, text: str, default_court: str = "") -> list[tuple[str, list[str]]]:
        """按法院名把正文切成段，每段内的行归属该法院，避免跨院串号。"""
        segments: list[tuple[str, list[str]]] = []
        if not text:
            return segments
        # 公众号的“法院名称：部门电话”常不是表格；文章还会同时出现已预置和
        # 未预置的法院。逐行识别标题可避免未预置法院的号码继续归入上一家法院，
        # 也避免 ``str.find`` 只找到同名法院的第一次出现。
        known_names = [str(row[0]) for row in conn.execute(
            "SELECT name FROM court_directory_courts ORDER BY LENGTH(name) DESC"
        )]
        headings: list[tuple[int, str]] = []
        offset = 0
        for raw_line in text.splitlines(keepends=True):
            line = norm(raw_line)
            # 仅接受行首的项目符号/编号后的法院名，避免正文中提及其他法院时误切段。
            match = re.search(
                r"^(?:[⚫●•#\-—、\d０-９一二三四五六七八九十\ufe0f]+[.．、:：]?\s*)?"
                r"([\u4e00-\u9fff]{2,16}(?:人民法院|法院))(?=[：:\s]|$)",
                line,
            )
            if match:
                candidate = match.group(1)
                # “韶关市乐昌市人民法院”一类带地市前缀的写法，优先归并到已
                # 收录的标准院名；没有标准名时仍保留原标题，待确认写入时建节点。
                court_name = next((name for name in known_names if name in candidate), "")
                if not court_name:
                    # 来源有时将基层院写作“湛江市廉江法院”；数据库标准名则是
                    # “廉江市人民法院”。仅在末段地名能唯一匹配时归并，避免猜测。
                    short_tail = re.sub(r"(?:人民)?法院$", "", candidate).rsplit("市", 1)[-1]
                    aliases = [name for name in known_names
                               if short_tail and re.sub(r"(?:人民)?法院$", "", name).startswith(short_tail)]
                    court_name = aliases[0] if len(aliases) == 1 else candidate
                headings.append((offset, court_name))
            offset += len(raw_line)
        for i, (idx, name) in enumerate(headings):
            end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
            lines = [norm(line) for line in text[idx:end].splitlines() if norm(line)]
            segments.append((name, lines))
        if not segments:
            segments.append((default_court, [norm(line) for line in text.splitlines() if norm(line)]))
        return segments

    court_pattern = re.compile(r"[\u4e00-\u9fff]{2,6}法庭")
    dept_names_sorted = sorted(("立案庭", "诉讼服务中心", "执行局", "执行一庭", "执行二庭", "执行三庭", "综合办公室", "审判管理办公室", "审管办", "政治部", "督察室", "法警队", "司法警察大队", "法院诉讼服务热线", "刑事审判庭", "民事审判一庭", "民事审判二庭", "民事审判三庭", "综合审判庭", "综审判庭", "立案大厅", "送达组", "民庭内勤", "刑庭内勤", "信访投诉", "立案窗口", "信访接待室", "值班室", "总机", "传真", *DEPT_ALIASES.keys()), key=len, reverse=True)

    def line_department(line: str) -> str:
        """本行若为部门行（部门名开头，可带括号说明或紧跟电话），返回部门名；否则返回空串。"""
        m = court_pattern.match(line)
        if m and (len(line) == len(m.group(0)) or line[len(m.group(0))] in "(（"):
            return m.group(0)
        # “执行电话：0757-88266655、88266680”“立案咨询：0757-12368”这类“职能+电话”行。
        m = re.match(r"^(立案咨询|立案|信访|执行|办公|值班|咨询)(?:电话)?[：:]", line)
        if m:
            return {"立案咨询": "立案庭", "立案": "立案庭", "信访": "信访接待室", "执行": "执行局", "办公": "综合办公室", "值班": "值班室", "咨询": "法院诉讼服务热线"}[m.group(1)]
        # “…快速搜索部门姓名/事项电话综合信息总机”这类行尾部门词，其电话通常在下一行。
        if line.endswith("总机") or line.endswith("综合信息"):
            return "总机"
        for name in dept_names_sorted:
            if not line.startswith(name):
                continue
            rest = line[len(name):]
            # 部门名后紧跟括号说明（立案庭（诉讼服务中心）…）、冒号、或直接是电话数字（送达组83009829）。
            if not rest or rest[0] in "(（：:，,、" or rest[0].isdigit():
                return name
        return ""

    def extract_phones(line: str, hotline: bool = False) -> list[str]:
        """提取行内电话；热线段允许 12368 等 5 位政务热线。"""
        if hotline:
            phones = HOTLINE_RE.findall(line)
        else:
            phones = PHONE_RE.findall(line)
            for extra in HOTLINE_RE.findall(line):
                if extra not in phones:
                    phones.append(extra)
        return phones

    def phones_on_line(line: str, hotline: bool = False) -> list[str]:
        """提取同一行号码，并补全“0759-2290369/2290556”后的省略区号。"""
        phones = extract_phones(line, hotline=hotline)
        prefix_match = re.search(r"(?<!\d)(0\d{2,3})\s*[-—－]\s*[2-9]\d{6,7}", line)
        if prefix_match and re.search(r"[/、,，]\s*[2-9]\d{6,7}(?!\d)", line):
            prefix = prefix_match.group(1)
            phones = [f"{prefix}-{phone}" if re.fullmatch(r"[2-9]\d{6,7}", normalized_phone(phone)) else phone
                      for phone in phones]
        return phones

    def local_extract(conn: Any, text: str, default_court: str = "") -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for court_name, lines in split_court_segments(conn, text, default_court):
            last_dept = ""
            for line in lines:
                inline_dept = line_department(line)
                if inline_dept:
                    last_dept = inline_dept
                # 本机 OCR 把数字误读成字母时，先做一次宽容修正，再提取电话与姓名，提升表格识别率。
                lenient = _ocr_phone_leniency(line)
                matches = list(PHONE_RE.finditer(lenient))
                phones = extract_phones(lenient, hotline=(inline_dept == "法院诉讼服务热线"))
                role_first = re.search(r"(?:法官助理|书记员|承办人|审判员|法官)\s*[：:]?\s*([\u4e00-\u9fff]{2,4})", lenient)
                name_first = re.search(r"([\u4e00-\u9fff]{2,4})\s*(?:法官助理|书记员|审判员|法官)", lenient)
                name_phone = re.search(r"([\u4e00-\u9fff]{2,4})[，,\s]*电话[：:]", lenient)
                # 无职务、无“电话：”字样的纯“姓名 电话”表格行（如 张焕然 86302380）。
                # 本机 OCR 会在列间残留竖线/空格，先剥离分隔符，再取电话前末尾的中文姓名。
                name_inline = None
                if lenient and not (role_first or name_first or name_phone) and matches and not line_department(line):
                    seg = re.sub(r"[|｜\s]+", "", lenient[:matches[0].start()])
                    nm = re.search(r"([\u4e00-\u9fff]{2,3})$", seg)
                    if nm and nm.group(1) not in NON_PERSON_NAMES:
                        name_inline = nm
                name = role_first.group(1) if role_first else (name_first.group(1) if name_first else (name_phone.group(1) if name_phone else (name_inline.group(1) if name_inline else "")))
                evidence = line.strip()
                if name in NON_PERSON_NAMES or name.endswith(("大队", "法庭", "立案庭", "执行局", "办公室", "法警队", "督察室", "政治部", "服务热线", "审判庭", "一庭", "二庭", "三庭", "四庭", "五庭", "六庭", "团队", "庭")) or any(w in name for w in ("查询", "咨询", "办公", "值班", "信访", "档案", "立案", "诉讼", "监督", "受理", "接待", "总机", "留言", "服务", "热线", "传真", "应急", "保全", "投诉", "大厅", "窗口", "送达", "内勤", "外勤", "电话", "信息", "综合", "部门", "号码", "事项", "保安", "值班室", "信访接待")) or any(token in name for token in ("法院", "审", "执行", "案件")):
                    name = ""
                # “庭长刘黎电话：010-85998733”等带职务前缀的姓名，剥离职务后保留姓名。
                if name:
                    for prefix in ("副庭长", "庭长", "副局长", "局长", "副院长", "院长", "审判长", "法官助理", "书记员", "审判员", "承办人", "内勤", "外勤", "法官"):
                        if name.startswith(prefix) and len(name) > len(prefix):
                            name = name[len(prefix):]
                            break
                # 部门名开头却紧接着大量“姓名+电话”连续串的行（如“立案庭（诉讼服务中心）朱江83009801吴宇晖…”）
                # 是人员列表而非部门电话行；本行无姓名可配对时，不能把整行电话当作该部门的号码，
                # 否则会把所有人员电话都挂到部门下。这类行由结构化解析处理，这里直接跳过。
                if not name and len([
                    m for m in re.findall(r"([\u4e00-\u9fff]{2,3})(?:[2-9]\d{6,7}|1[3-9]\d{9})", line)
                    if m not in NON_PERSON_NAMES
                    and not any(w in m for w in ("法院", "电话", "通讯", "人民", "部门", "法官", "助理", "庭长", "局长", "查询", "咨询", "办公", "值班", "信访", "档案", "立案", "诉讼", "监督", "受理", "接待", "总机", "留言", "服务", "热线", "传真", "应急", "保全", "投诉", "大厅", "窗口", "送达", "内勤", "外勤", "信息", "综合", "号码", "事项"))
                    and not m.endswith(("庭", "局", "组", "厅", "窗口", "室", "队", "所", "内勤", "外勤"))
                ]) >= 2:
                    continue
                position = next((x for x in ("法官助理", "书记员", "法官", "审判员", "承办人") if x in lenient), "")
                department = inline_dept or last_dept
                emails = EMAIL_RE.findall(line)
                for phone in phones:
                    entries.append({"court": court_name, "department": department, "name": name, "position": position, "phone": phone, "email": emails[0] if emails else "", "evidence": evidence})
        return entries

    def table_directory_extract(conn: Any, text: str, default_court: str = "") -> list[dict[str, str]]:
        """解析 OCR 输出的“姓名｜外线电话｜内线电话”表格。

        通用正文解析会把表格标题、列标题和每一行拼成连续文字，从而让部门只落到
        少数联系人，甚至把内线号码当作另一条记录。这里以列标题为锚点逐行取第一
        个有效电话（外线），并把表格标题中的庭室信息应用到整张表。
        """
        rows = [line.strip() for line in (text or "").splitlines() if norm(line)]
        header_index = next((i for i, line in enumerate(rows)
                             if "姓名" in line and "电话" in line), -1)
        if header_index < 0:
            return []

        def title_department() -> str:
            title = "".join(rows[:header_index])
            # 旧版通讯录常以“刑庭通讯录”“民一庭通讯录”为标题；补足常用简称。
            aliases = {"刑庭": "刑事审判庭", "民庭": "民事审判庭"}
            for short, full in aliases.items():
                if short in title:
                    return full
            candidates = sorted((*DEPT_ALIASES.keys(), "刑事审判庭", "民事审判庭",
                                 "执行局", "立案庭", "综合审判庭"), key=len, reverse=True)
            matched = next((value for value in candidates if value in title), "")
            return canonical_department(matched)

        department = title_department()
        entries: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for line in rows[header_index + 1:]:
            lenient = _ocr_phone_leniency(line)
            phone_matches = list(PHONE_RE.finditer(lenient))
            if not phone_matches:
                continue
            # 表格第二列是外线电话；最后一列为内线分机，不能写入联系人电话。
            phone = phone_matches[0].group(0)
            if not valid_phone(phone):
                continue
            name_cell = lenient[:phone_matches[0].start()]
            name_cell = re.sub(r"[（(〔\[][^）)〕\]]*[）)〕\]]", "", name_cell)
            name = "".join(re.findall(r"[\u4e00-\u9fff]", name_cell))
            if not name:
                continue
            key = (name, normalized_phone(phone))
            if key in seen:
                continue
            seen.add(key)
            entries.append({"court": default_court, "department": department, "name": name,
                            "position": "", "phone": phone, "email": "", "evidence": line})
        # 至少三行才可确信这是人员表格，避免把正文中的偶然列标题误作通讯录。
        return entries if len(entries) >= 3 else []

    def html_table_directory_extract(text: str, default_court: str = "") -> list[dict[str, str]]:
        """解析抓取器保留的公众号 HTML 表格行。

        规则同时覆盖常见的合并单元格和分机写法：部门单元格纵向合并时，后续
        ``姓名\t分机`` 行沿用本组部门；正文说明了“020-8300+以下4位号码”时，
        自动把四位分机补为可拨打的完整号码。每名人员仍只与自己所在行的号码
        配对，绝不从下一行借用号码。
        """
        # 公众号常把拨号规则写在表格前，例如“拨打方式为 020-8300 + 以下4位
        # 号码”。该前缀只用于表格中独立的短分机，正常座机和手机号不受影响。
        extension_prefix = ""
        prefix_match = re.search(
            r"((?:0\d{2,3}\s*[-—－]\s*)?\d{3,5})\s*\+\s*(?:以下\s*)?\d*\s*位(?:号码|数)?",
            text or "",
        )
        if prefix_match:
            candidate = normalized_phone(prefix_match.group(1))
            if 4 <= len(candidate) <= 8:
                extension_prefix = candidate

        entries: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        current_department = ""
        for line in (text or "").splitlines():
            cells = [norm(value) for value in line.split("\t")]
            if len(cells) < 2:
                continue
            # 有 rowspan 的表格，首行是“部门\t姓名\t电话”，同一部门的后续行
            # 只会保留“姓名\t电话”。
            if len(cells) >= 3:
                department, name, phone = cells[0], cells[1], cells[2]
                compact_header = tuple(re.sub(r"\s+", "", value) for value in (department, name, phone))
                if compact_header == ("部门", "人员", "电话号码") or compact_header == ("部门", "姓名", "电话"):
                    current_department = ""
                    continue
                if department:
                    current_department = department
            else:
                if not current_department:
                    continue
                department, name, phone = current_department, cells[0], cells[1]

            digits = normalized_phone(phone)
            if extension_prefix and re.fullmatch(r"\d{4,6}", digits):
                phone = extension_prefix + digits
            if not valid_phone(phone):
                continue
            # 表格中的“姓名”列是原始来源字段。只要非空就原样保留，不对字数、
            # 字符集或关键词做限制；功能名称也可能是公开通讯录中有价值的联系人标签。
            is_person = bool(name)
            key = (canonical_department(department), name if is_person else "", normalized_phone(phone))
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                "court": default_court,
                "department": canonical_department(department),
                "name": name if is_person else "",
                "position": "",
                "phone": phone,
                "email": "",
                "evidence": line,
            })
        return entries if len(entries) >= 2 else []

    def structured_directory_extract(text: str, default_court: str = "") -> list[dict[str, str]]:
        """解析公众号常见的连续排版通讯录，按“职务 + 姓名 + 电话”就近配对。"""
        if not default_court:
            detected = detect_court_names(text)
            default_court = detected[0] if detected else ""
        if not default_court:
            return []
        compact = re.sub(r"\s+", "", text or "")
        if not compact:
            return []
        position_terms = "法官助理|书记员|审判员|副庭长|庭长|副局长|局长|辅助人员|法警|内勤|外勤|法官|助理"
        phone_pattern = r"((?:0\d{2,3}[-— ]?)?[2-9]\d{6,7}|1[3-9]\d{9})"
        role_first = re.compile(rf"({position_terms})[：:]?([\u4e00-\u9fff]{{2,3}})[（(]*[^0-9\u4e00-\u9fff]{{0,8}}{phone_pattern}")
        name_first = re.compile(rf"(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{{2,3}})({position_terms})[：:]?[^0-9\u4e00-\u9fff]{{0,8}}{phone_pattern}")
        department_markers = tuple(sorted((*DEPT_ALIASES.keys(), "民事审判第一庭", "民事审判第二庭", "民事审判第三庭", "民事审判一庭", "民事审判二庭", "民事审判三庭", "刑事审判庭", "民事庭", "刑庭", "少年庭", "速裁庭", "执行局", "立案庭", "立案大厅", "送达组", "民庭内勤", "刑庭内勤", "信访投诉", "立案窗口", "诉前联调室", "执行一庭", "执行二庭", "执行三庭"), key=len, reverse=True))
        entries: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def nearby_department(index: int) -> str:
            prefix = compact[max(0, index - 120):index]
            found = [(prefix.rfind(marker), marker) for marker in department_markers if prefix.rfind(marker) >= 0]
            m = court_pattern.search(prefix)
            if m:
                found.append((m.start(), m.group(0)))
            return canonical_department(max(found)[1]) if found else ""

        def append(name: str, position: str, phone: str, index: int, evidence: str, department: str = "") -> None:
            # “庭长刘黎电话：010-85998733”这类带职务前缀的姓名，剥离职务后按姓名入库，
            # 与 role_first 模式提取的“刘黎”去重合并，避免一人两条。
            for prefix in ("副庭长", "庭长", "副局长", "局长", "副庭长", "院长", "审判长", "法官助理", "书记员", "审判员", "承办人", "内勤", "外勤", "法官"):
                if name.startswith(prefix) and len(name) > len(prefix):
                    name = name[len(prefix):]
                    break
            non_person_cells = set(department_markers) | {"传真号", "扫描员", "银行收费", "调解室", "内勤", "咨询", "电话", "总机", "传真", "大厅", "窗口", "送达组", "信访投诉"}
            # 部门名残片（如“司法警察大队”被拆成“法警+察大队”）不能当人员入库。
            dept_suffix = name.endswith(("大队", "法庭", "立案庭", "执行局", "办公室", "法警队", "督察室", "政治部", "服务热线", "审判庭", "一庭", "二庭", "三庭", "四庭", "五庭", "六庭", "团队", "庭", "组", "厅", "窗口", "室", "内勤", "外勤"))
            function_words = ("查询", "咨询", "办公", "值班", "信访", "档案", "立案", "诉讼", "监督", "受理", "接待", "总机", "留言", "服务", "热线", "传真", "应急", "保全", "投诉", "大厅", "窗口", "送达", "内勤", "外勤", "电话", "信息", "综合", "部门", "号码", "事项", "庭内勤", "值班室", "信访接待")
            if not valid_phone(phone) or name in NON_PERSON_NAMES or name in non_person_cells or dept_suffix or any(w in name for w in function_words) or any(token in name for token in ("法院", "电话", "通讯", "人民", "部门", "庭长", "局长", "法官", "助理", "法庭", "保安", "总机", "传真", "值班", "信访", "送达", "大厅", "窗口", "内勤", "外勤")):
                return
            key = (name, normalized_phone(phone))
            if key in seen:
                return
            seen.add(key)
            entries.append({"court": default_court, "department": canonical_department(department) if department else nearby_department(index), "name": name, "position": position, "phone": phone, "evidence": evidence[:240]})

        for match in role_first.finditer(compact):
            append(match.group(2), match.group(1), match.group(3), match.start(), match.group(0))
        for match in name_first.finditer(compact):
            append(match.group(1), match.group(2), match.group(3), match.start(), match.group(0))
        # 很多法院通讯录就是“部门 + 姓名 + 电话”的三列表格，姓名旁没有职务。
        # 这类记录不能依赖职务词，否则会遗漏绝大多数立案庭、速裁庭等工作人员。
        department_pattern = "|".join(re.escape(marker) for marker in department_markers)
        generic_row = re.compile(rf"({department_pattern})([\u4e00-\u9fff]{{2,3}}){phone_pattern}")
        for match in generic_row.finditer(compact):
            append(match.group(2), "", match.group(3), match.start(), match.group(0), match.group(1))
        # “刘胜军电话：010-85998944”“张伟 电话：010-85998929”“黄泽群，电话：010-86377507”等无职务的姓名+电话行。
        # 按原始行匹配：这类行通常独占一行，行内匹配不会把“房间刘胜军电话”粘连误配。
        name_phone = re.compile(rf"([\u4e00-\u9fff]{{2,4}})[，,\s]*电话[：:]?\s*{phone_pattern}")
        for line in re.split(r"[\n；;]", text or ""):
            for match in name_phone.finditer(line):
                append(match.group(1), "", match.group(2), compact.find(line), line.strip())
        # 微信编辑器常把整段“姓名+电话”放进同一段落，人名与号码之间无空格/换行，
        # 例如“立案庭（诉讼服务中心）朱江83009801吴宇晖83009662…”。
        # 以部门标记/法庭名把紧凑文本切块，块内按“姓名(2-3字)+电话”贪心配对。
        # 注意：块边界只放真正的部门节点，不能把“送达组/民庭内勤/信访投诉”等职能电话词
        # 当作人员边界，否则会把紧跟在职能电话后的人员误归入该职能部门。
        compact_markers = tuple(sorted((*DEPT_ALIASES.keys(), "民事审判第一庭", "民事审判第二庭", "民事审判第三庭",
                                        "民事审判一庭", "民事审判二庭", "民事审判三庭", "刑事审判庭", "民事庭", "刑庭",
                                        "少年庭", "速裁庭", "执行局", "执行一庭", "执行二庭", "执行三庭", "立案庭",
                                        "诉讼服务中心", "诉前联调室", "综合审判庭", "综审判庭"), key=len, reverse=True))
        marker_hits: list[tuple[int, str]] = []
        for marker in compact_markers:
            pos = 0
            while True:
                i = compact.find(marker, pos)
                if i < 0:
                    break
                # 跳过括号内的部门说明（如“立案庭（诉讼服务中心）”里的“诉讼服务中心”）。
                if compact[i - 1] not in ("（", "("):
                    marker_hits.append((i, marker))
                pos = i + 1
        for m in court_pattern.finditer(compact):
            if compact[m.start() - 1] not in ("（", "("):
                marker_hits.append((m.start(), m.group(0)))
        marker_hits.sort(key=lambda x: x[0])
        block_markers: dict[int, str] = {}
        for pos, marker in marker_hits:
            if pos not in block_markers or len(marker) > len(block_markers[pos]):
                block_markers[pos] = marker
        block_positions = sorted(block_markers)
        name_tel = re.compile(rf"([\u4e00-\u9fff]{{2,3}})([2-9]\d{{6,7}}|1[3-9]\d{{9}})")
        for i, pos in enumerate(block_positions):
            end = block_positions[i + 1] if i + 1 < len(block_positions) else len(compact)
            seg = compact[pos:end]
            dept = block_markers[pos]
            for match in name_tel.finditer(seg):
                append(match.group(1), "", match.group(2), pos + match.start(), match.group(0), dept)
        return entries

    def line_directory_extract(conn: Any, text: str, default_court: str = "") -> list[dict[str, str]]:
        """解析“部门／职务／姓名／电话”逐行排版的通讯录。

        公众号文章常将每个字段拆成独立段落。例如“法官助理、示七某、83210000”
        会被普通逐行扫描误判为部门电话。这里仅在姓名紧邻电话时建立人员记录，
        并把同一庭室下的团队、窗口和传真等子标题保留为上下文，不作为部门覆盖。
        """
        department_titles = tuple(sorted((
            "立案庭", "刑事审判第一庭", "刑事审判第二庭", "刑事审判第三庭",
            "少年家事审判庭", "民事审判庭", "商事审判庭", "金融审判庭",
            "涉外商事审判庭", "房地产审判庭", "行政审判庭", "审判监督庭",
            "执行局", "审判管理办公室", "综合办公室", "政治部", "研究室",
            "司法警察大队", "赔偿委员会办公室", "环境资源审判庭", "知识产权审判庭",
        ), key=len, reverse=True))
        role_titles = {
            "法官助理", "书记员", "审判员", "法官", "员额法官", "返聘法官", "法警",
            "速录员", "辅助人员", "助理", "内勤", "外勤", "庭长", "副庭长", "院长",
            "副院长", "局长", "副局长", "审判长", "组长", "负责人",
        }
        one_person_roles = {"庭长", "副庭长", "院长", "副院长", "局长", "副局长", "审判长", "组长", "负责人"}
        non_person_labels = role_titles | {
            "传真", "传真号", "传真号码", "电话传真号", "办公电话", "诉讼服务热线",
            "团队", "综合组", "指导组", "速录组", "内勤组", "一审立案组", "二审立案组",
            "信访组", "材料接收室", "日常接访室", "律师接访室", "律师调解工作室",
            "东导诉区", "西导诉区", "查询咨询", "诉讼材料收转", "诉讼材料扫描",
            "便民服务岗", "法律咨询援助岗", "邮政专递", "立案窗口", "公证司法辅助",
            "诉讼费缴纳",
        }

        def department_title(line: str) -> str:
            for title in department_titles:
                if line == title or line.startswith(f"{title}（") or line.startswith(f"{title}("):
                    return canonical_department(title)
            return ""

        def role_title(line: str) -> tuple[str, bool]:
            value = re.sub(r"[（(].*?[）)]", "", line)
            # “员额法官（组长）”中的组长是团队说明，不能令后续所有人员都成为组长。
            if value == "员额法官":
                return value, False
            if value in role_titles:
                return value, value in one_person_roles
            return "", False

        def person_name(line: str) -> str:
            value = re.sub(r"[（(].*?[）)]", "", line)
            # 逐行通讯录中的姓名字段不限制字数和内容；是否属于人员由该行与电话
            # 的结构关系决定，而不是按预设词表否决来源原文。
            value = value.strip()
            # 这是表格列/线路标签而非姓名字段，排除不属于姓名内容校验。
            if value.endswith(("外线", "内线", "电话", "传真")):
                return ""
            return value

        entries: list[dict[str, str]] = []
        for court_name, lines in split_court_segments(conn, text, default_court):
            department = ""
            base_position = ""
            position = ""
            one_shot_position = False
            pending_name = ""
            court_general_pending = False
            department_phone_continuation = False
            for line in lines:
                # 分段首行通常就是“1.某某人民法院：”。它是归属标题，绝不能作为
                # 下一行“立案庭：电话”的联系人姓名；若标题自身或紧随下一行有号码，
                # 则以“法院总机”这一部门条目保存。
                is_court_heading = bool(re.search(r"[\u4e00-\u9fff]{2,16}(?:人民法院|法院)[：:]?", line))
                if is_court_heading:
                    phones = [phone for phone in phones_on_line(line) if valid_phone(phone)]
                    if phones:
                        for phone in phones:
                            entries.append({"court": court_name, "department": "法院总机", "name": "",
                                            "position": "", "phone": phone, "evidence": line})
                    department = "法院总机"
                    base_position = position = ""
                    one_shot_position = False
                    pending_name = ""
                    court_general_pending = not bool(phones)
                    department_phone_continuation = False
                    continue

                # “立案庭：0757-…”、“执行局：0757-…”属于部门电话，不是前一行
                # 标题所述法院的人员电话。先识别部门，阻止其被 pending_name 吸收。
                inline_department = line_department(line)
                if inline_department:
                    department = canonical_department(inline_department)
                    base_position = position = ""
                    one_shot_position = False
                    pending_name = ""
                    court_general_pending = False
                    phones = [phone for phone in phones_on_line(line, hotline=(department == "法院诉讼服务热线")) if valid_phone(phone)]
                    for phone in phones:
                        entries.append({"court": court_name, "department": department, "name": "",
                                        "position": "", "phone": phone, "evidence": line})
                    # 紧跟的纯号码行（如“执行局：0757-88266655”下一行
                    # “0757-88266680”）仍属于同一部门。
                    department_phone_continuation = bool(phones)
                    continue

                title = department_title(line)
                if title:
                    department = title
                    base_position = position = ""
                    one_shot_position = False
                    pending_name = ""
                    court_general_pending = False
                    department_phone_continuation = False
                    continue

                role, is_one_shot = role_title(line)
                if role:
                    position = role
                    one_shot_position = is_one_shot
                    if not is_one_shot:
                        base_position = role
                    pending_name = ""
                    department_phone_continuation = False
                    continue

                phones = [phone for phone in phones_on_line(line) if valid_phone(phone)]
                if phones:
                    name = pending_name
                    # 同一行的“姓名 电话”表格仍可由此分支处理。
                    direct = re.match(r"^([\u4e00-\u9fff]{2,4})[，,、\s]*((?:0\d{2,3}[-— ]?)?[2-9]\d{6,7}|1[3-9]\d{9})$", line)
                    if direct:
                        name = person_name(direct.group(1))
                    if name:
                        for phone in phones:
                            entries.append({"court": court_name, "department": department, "name": name,
                                            "position": position, "phone": phone, "evidence": line})
                    elif court_general_pending:
                        for phone in phones:
                            entries.append({"court": court_name, "department": "法院总机", "name": "",
                                            "position": "", "phone": phone, "evidence": line})
                    elif department_phone_continuation and department:
                        for phone in phones:
                            entries.append({"court": court_name, "department": department, "name": "",
                                            "position": "", "phone": phone, "evidence": line})
                    pending_name = ""
                    court_general_pending = False
                    department_phone_continuation = False
                    if one_shot_position:
                        position = base_position
                        one_shot_position = False
                    continue

                candidate = person_name(line)
                if candidate:
                    pending_name = candidate
                    department_phone_continuation = False
                else:
                    # 新的栏目说明不能与前一位人员跨行配对。
                    pending_name = ""
                    department_phone_continuation = False
        return entries

    def case_extract(conn: Any, text: str, default_court: str = "") -> list[dict[str, str]]:
        """仅从案件资料中提取明确标为经办人员的记录。

        案件备注常包含当事人、金额和流程文字；不能把它们当成法院树或人员资料。
        因此，案件同步必须已有系统内的法院匹配，且姓名旁须出现职务标记。
        """
        if not default_court or not court_id(conn, default_court):
            return []
        lines = [norm(line) for line in (text or "").splitlines() if norm(line)]
        results: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()

        def phones_near(index: int) -> list[str]:
            scope = lines[index]
            if not PHONE_RE.findall(scope):
                # 仅配对紧随其后的“电话：”字段；不跨越普通备注文字乱配号码。
                for following in lines[index + 1:index + 3]:
                    if re.match(r"(?:联系电话|电话)[:：]", following):
                        scope = following
                        break
                    if re.match(r"(?:姓名|联系人|法官助理|书记员|审判员|承办法官|法官)[:：]", following):
                        break
            return [phone for phone in PHONE_RE.findall(scope) if valid_phone(phone)]

        def add(name: str, position: str, index: int) -> None:
            name = norm(name)
            if not name:
                return
            for phone in phones_near(index):
                key = (name, position, normalized_phone(phone))
                if key in seen:
                    continue
                seen.add(key)
                results.append({"court": default_court, "department": "", "name": name, "position": position, "phone": phone, "evidence": lines[index]})

        # “法官：示七某”“书记员示七某”“示七某法官”等明确身份格式。
        role_first = re.compile(r"(?<![\u4e00-\u9fff])(法官助理|书记员|审判员|承办法官|法官|承办人)\s*[：:]?\s*([\u4e00-\u9fff]{2,3})")
        name_first = re.compile(r"(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{2,3})\s*(法官助理|书记员|审判员|法官)")
        for index, line in enumerate(lines):
            for match in role_first.finditer(line):
                role = "法官" if match.group(1) == "承办法官" else match.group(1)
                add(match.group(2), role, index)
            for match in name_first.finditer(line):
                add(match.group(1), match.group(2), index)
        return results

    def department_directory_extract(conn: Any, text: str, default_court: str = "") -> list[dict[str, str]]:
        """识别'部门名 + 联系电话'的职能部门通讯录条目（不依赖姓名）。

        公众号排版常为“部门名 / 电话”交替的表格；按法院分段后，
        把部门名与紧跟的电话行配对。
        """
        entries: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for court_name, lines in split_court_segments(conn, text, default_court):
            for i, line in enumerate(lines):
                if "地址" in line or "保安" in line:
                    continue
                dept = line_department(line)
                if not dept:
                    continue
                phones = extract_phones(line, hotline=(dept == "法院诉讼服务热线"))
                if not phones:
                    for j in range(i + 1, min(i + 8, len(lines))):
                        nxt = lines[j]
                        if "地址" in nxt or re.match(r"^(部门|办公电话|电话|法院)", nxt):
                            break
                        # “臧德胜电话：010-85998638”这类行是人员电话，由人员提取处理，不并入部门电话。
                        if re.match(r"[\u4e00-\u9fff]{2,4}[，,\s]*电话[：:]", nxt):
                            break
                        # 下一行已是新的部门行（如“送达组83009829…”），其电话交给它自己处理，不能跨部门累积。
                        if line_department(nxt):
                            break
                        got = extract_phones(nxt, hotline=(dept == "法院诉讼服务热线"))
                        if not got:
                            break
                        phones.extend(got)
                # 行内出现多个“姓名+电话”连续串（如“立案庭（诉讼服务中心）朱江83009801吴宇晖83009662…”）
                # 说明该行是人员列表而非部门电话行，全部交给人员提取，避免把每个人员的号码误挂到部门下。
                # 匹配到的姓名需排除“送达组/民庭内勤/传真/投诉”等职能词，避免部门电话行被误判为人员行。
                _person_marks = re.findall(r"([\u4e00-\u9fff]{2,3})(?:[2-9]\d{6,7}|1[3-9]\d{9})", line)
                _person_marks = [m for m in _person_marks
                                 if m not in NON_PERSON_NAMES
                                 and not any(w in m for w in ("法院", "电话", "通讯", "人民", "部门", "法官", "助理", "庭长", "局长"))
                                 and not any(w in m for w in ("查询", "咨询", "办公", "值班", "信访", "档案", "立案", "诉讼", "监督", "受理", "接待", "总机", "留言", "服务", "热线", "传真", "应急", "保全", "投诉", "大厅", "窗口", "送达", "内勤", "外勤", "电话", "信息", "综合", "部门", "号码", "事项", "庭内勤", "值班室"))
                                 and not m.endswith(("庭", "局", "组", "厅", "窗口", "室", "队", "所", "内勤", "外勤"))]
                if len(_person_marks) >= 2:
                    continue
                for phone in phones:
                    key = (court_name, canonical_department(dept), normalized_phone(phone))
                    if key in seen:
                        continue
                    seen.add(key)
                    entries.append({"court": court_name, "department": dept, "name": "", "position": "", "phone": phone, "email": "", "evidence": line})
        return entries

    def dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按 法院+部门+电话+姓名 去重；部门条目排在前面，重复时保留部门行证据。"""
        seen: set[tuple[str, str, str, str]] = set()
        out: list[dict[str, Any]] = []
        for e in entries:
            key = (norm(e.get("court")), canonical_department(e.get("department")), normalized_phone(e.get("phone")), norm(e.get("name")))
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
        return out

    async def extract_entries(conn: Any, raw: str, default_court: str = "") -> list[dict[str, Any]]:
        html_table_entries = html_table_directory_extract(raw, default_court)
        if html_table_entries:
            return html_table_entries
        table_entries = table_directory_extract(conn, raw, default_court)
        if table_entries:
            return table_entries
        line_based = line_directory_extract(conn, raw, default_court)
        # 多个相邻“姓名—电话”对已足以确认是分行通讯录。此时紧凑文本解析会跨越
        # 段落边界，把“内勤组王智”“刑一庭外线”等栏目文字误当姓名，故不再混用。
        separated_directory = len(line_based) >= 3
        structured = [] if separated_directory else structured_directory_extract(raw, default_court)
        departments = [] if separated_directory else department_directory_extract(conn, raw, default_court)
        # “部门／职务／姓名／电话”分行的公众号正文必须优先用相邻行配对。
        # local_extract 为 OCR 和紧凑表格兜底，会将这种正文中大量独立电话行误挂到最近部门，
        # 因此仅在未发现任何可靠的逐行人员记录时启用它。
        local = [] if separated_directory else local_extract(conn, raw, default_court)
        # 邮箱/电话表格照片、公众号连续排版等混杂来源：逐行配对 + 结构化配对 + 部门条目互补。
        merged = dedupe_entries(line_based + structured + departments + local)
        if merged:
            return merged
        try:
            result, _ = await call_ai_with_fallback(DEFAULT_AI_MODEL, [{"role": "system", "content": "从中国法院公开通讯录中提取联系人。仅返回 JSON 数组，每项字段 court,department,name,position,phone,email,observed_at,evidence；没有明确字段用空字符串，禁止猜测。"}, {"role": "user", "content": raw[:24000]}], temperature=0, max_tokens=2200)
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            start, end = content.find("["), content.rfind("]")
            data = json.loads(content[start:end + 1]) if start >= 0 and end >= start else []
            items = [x for x in data if isinstance(x, dict) and valid_phone(x.get("phone"))]
            for item in items:
                item["evidence"] = norm(item.get("evidence"))[:800]
                if not norm(item.get("court")):
                    item["court"] = default_court
            return dedupe_entries(departments + (items or local))
        except Exception:
            return dedupe_entries(departments + local)

    def public_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HTTPException(status_code=400, detail="仅支持公开 HTTP/HTTPS 链接")
        if parsed.hostname.lower() in {"localhost", "0.0.0.0"}:
            raise HTTPException(status_code=400, detail="不允许访问本机地址")
        try:
            for result in socket.getaddrinfo(parsed.hostname, None):
                if ipaddress.ip_address(result[4][0]).is_private or ipaddress.ip_address(result[4][0]).is_loopback:
                    raise HTTPException(status_code=400, detail="不允许访问内网地址")
        except socket.gaierror:
            raise HTTPException(status_code=400, detail="无法解析该网址")

    async def fetch_url(url: str) -> tuple[str, str, str]:
        public_url(url)
        # 与知识库的“网页链接”入口共用公众号动态读取器。该读取器以普通浏览器
        # 打开公开文章、提取已呈现的正文；并不绕过登录、人机验证或访问限制。
        if urlparse(url).hostname and urlparse(url).hostname.lower().endswith("mp.weixin.qq.com") and weixin_fetcher:
            try:
                article = await weixin_fetcher(url)
                content = str(article.get("content") or "")
                soup = BeautifulSoup(content, "html.parser")
                raw = soup.get_text("\n", strip=True)
                # 动态抓取器已从公众号 table 中逐行提取单元格。把它追加为带制表符的
                # 结构化行，让下方解析优先使用同一 tr 内的部门、姓名和电话，避免
                # 被上面的扁平正文重新拆散。
                table_lines = []
                for row in article.get("directory_rows") or []:
                    # rowspan/colspan 会使同一部门的后续行只有“姓名、电话”两格；
                    # 保留它们交给表格识别规则继承部门并补全分机。
                    if not isinstance(row, (list, tuple)) or len(row) < 2:
                        continue
                    table_lines.append("\t".join(str(value or "").replace("\t", " ").replace("\n", " ") for value in row))
                if table_lines:
                    raw = f"{raw}\n\n" + "\n".join(table_lines)
                if len(raw) >= 40:
                    return (norm(article.get("title")) or "微信公众号文章", raw, normalize_published(article.get("publish_time")))
            except Exception as exc:
                # 继续使用下方普通抓取；若仍被拦截，会给出准确提示。
                dynamic_error = str(exc)
            else:
                dynamic_error = ""
        else:
            dynamic_error = ""
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "APEX-CourtDirectory/1.0"}) as client:
            response = await client.get(url)
            response.raise_for_status()
        if "antispider" in str(response.url) or "wappoc_appmsgcaptcha" in str(response.url):
            suffix = f"（知识库网页读取也未取得正文：{dynamic_error}）" if dynamic_error else ""
            raise HTTPException(status_code=422, detail=f"该公众号链接当前未取得公开正文{suffix}。请在浏览器打开文章后，将正文粘贴到下方“文章正文”再分析。")
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]): tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else "公开法院通讯录"
        return (title, soup.get_text("\n", strip=True), extract_publish_time(soup))

    def query_results(conn: Any, q: str, court: int, department: int, position: str, include_history: bool) -> tuple[list[dict[str, Any]], int]:
        clauses, params = ["1=1"], []
        if court: clauses.append("p.court_id=?"); params.append(court)
        if department: clauses.append("a.department_id=?"); params.append(department)
        if position: clauses.append("a.position LIKE ?"); params.append(f"%{position}%")
        if q: clauses.append("(p.name LIKE ? OR c.name LIKE ? OR d.name LIKE ? OR ct.phone LIKE ? OR d.aliases_json LIKE ?)"); params.extend([f"%{q}%"] * 5)
        if not include_history: clauses.append("COALESCE(p.manual_status,'') NOT IN ('departed') AND COALESCE(ct.manual_status,'') NOT IN ('invalid','disabled')")
        person_total = int(conn.execute(f"""SELECT COUNT(DISTINCT p.id)
              FROM court_directory_people p JOIN court_directory_courts c ON c.id=p.court_id
              LEFT JOIN court_directory_affiliations a ON a.person_id=p.id LEFT JOIN court_directory_departments d ON d.id=a.department_id
              LEFT JOIN court_directory_contacts ct ON ct.owner_kind='person' AND ct.owner_id=p.id
              WHERE {' AND '.join(clauses)}""", params).fetchone()[0])
        rows = conn.execute(f"""SELECT p.id person_id,p.name,c.id court_id,c.name court_name,
                 (SELECT a2.department_id FROM court_directory_affiliations a2 WHERE a2.person_id=p.id AND COALESCE(a2.ended_at,'')='' ORDER BY a2.effective_at DESC, a2.id DESC LIMIT 1) department_id,
                 (SELECT d2.name FROM court_directory_affiliations a2 LEFT JOIN court_directory_departments d2 ON d2.id=a2.department_id WHERE a2.person_id=p.id AND COALESCE(a2.ended_at,'')='' ORDER BY a2.effective_at DESC, a2.id DESC LIMIT 1) department,
                 (SELECT a3.position FROM court_directory_affiliations a3 WHERE a3.person_id=p.id AND COALESCE(a3.ended_at,'')='' ORDER BY a3.effective_at DESC, a3.id DESC LIMIT 1) position,
                 p.manual_status person_status,
                 GROUP_CONCAT(DISTINCT ct.phone) phones,GROUP_CONCAT(DISTINCT ct.email) emails,GROUP_CONCAT(DISTINCT ct.manual_status) contact_statuses,
                 MAX(COALESCE(s.published_at,o.observed_at,s.collected_at)) latest_at
              FROM court_directory_people p JOIN court_directory_courts c ON c.id=p.court_id
              LEFT JOIN court_directory_affiliations a ON a.person_id=p.id LEFT JOIN court_directory_departments d ON d.id=a.department_id
              LEFT JOIN court_directory_contacts ct ON ct.owner_kind='person' AND ct.owner_id=p.id LEFT JOIN court_directory_contact_observations o ON o.contact_id=ct.id LEFT JOIN court_directory_sources s ON s.id=o.source_id
              WHERE {' AND '.join(clauses)} GROUP BY p.id ORDER BY latest_at DESC,p.name LIMIT 500""", params).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["entity_kind"] = "person"
            results.append(item)
        department_total = 0
        if not position:
            dclauses, dparams = ["1=1"], []
            if court: dclauses.append("d.court_id=?"); dparams.append(court)
            if department: dclauses.append("d.id=?"); dparams.append(department)
            if q: dclauses.append("(d.name LIKE ? OR c.name LIKE ? OR ct.phone LIKE ? OR d.aliases_json LIKE ?)"); dparams.extend([f"%{q}%"] * 4)
            if not include_history: dclauses.append("COALESCE(ct.manual_status,'') NOT IN ('invalid','disabled')")
            department_total = int(conn.execute(f"""SELECT COUNT(DISTINCT d.id)
                 FROM court_directory_departments d JOIN court_directory_courts c ON c.id=d.court_id
                 JOIN court_directory_contacts ct ON ct.owner_kind='department' AND ct.owner_id=d.id
                 WHERE {' AND '.join(dclauses)}""", dparams).fetchone()[0])
            dept_rows = conn.execute(f"""SELECT NULL person_id,d.name,d.id department_id,d.name department,c.id court_id,c.name court_name,
                    '' position,'' person_status,
                    GROUP_CONCAT(DISTINCT ct.phone) phones,GROUP_CONCAT(DISTINCT ct.email) emails,GROUP_CONCAT(DISTINCT ct.manual_status) contact_statuses,
                    MAX(COALESCE(s.published_at,o.observed_at,s.collected_at)) latest_at
                 FROM court_directory_departments d JOIN court_directory_courts c ON c.id=d.court_id
                 JOIN court_directory_contacts ct ON ct.owner_kind='department' AND ct.owner_id=d.id
                 LEFT JOIN court_directory_contact_observations o ON o.contact_id=ct.id LEFT JOIN court_directory_sources s ON s.id=o.source_id
                 WHERE {' AND '.join(dclauses)} GROUP BY d.id ORDER BY latest_at DESC LIMIT 300""", dparams).fetchall()
            for row in dept_rows:
                item = dict(row)
                item["entity_kind"] = "department"
                results.append(item)
        return sorted(results, key=lambda item: item.get("latest_at") or "", reverse=True)[:500], person_total + department_total

    def backfill_cases() -> dict[str, int]:
        count = {"sources": 0, "contacts": 0}
        with get_db() as conn:
            queries = [
                ("案件", "SELECT c.id,c.title,'' case_number,COALESCE((SELECT cn2.court FROM case_manager_case_numbers cn2 WHERE cn2.case_id=c.id AND COALESCE(cn2.court,'')<>'' LIMIT 1),'') court,c.court_contact text,c.updated_at FROM case_manager_cases c WHERE COALESCE(c.court_contact,'')<>'' AND (SELECT COUNT(DISTINCT NULLIF(cn3.court,'')) FROM case_manager_case_numbers cn3 WHERE cn3.case_id=c.id)=1"),
                ("案件", "SELECT c.id,c.title,'' case_number,cn.court,cn.handler_contact text,c.updated_at FROM case_manager_case_numbers cn JOIN case_manager_cases c ON c.id=cn.case_id WHERE COALESCE(cn.handler_contact,'')<>''"),
                ("开庭提醒", "SELECT c.id,c.title,h.case_no,h.court,h.court_contact text,h.updated_at FROM case_manager_hearings h JOIN case_manager_cases c ON c.id=h.case_id WHERE COALESCE(h.court_contact,'')<>''"),
                ("上诉节点", "SELECT c.id,c.title,a.case_no,a.court,a.court_contact text,a.updated_at FROM case_manager_appeals a JOIN case_manager_cases c ON c.id=a.case_id WHERE COALESCE(a.court_contact,'')<>''"),
            ]
            for label, sql in queries:
                try: rows = conn.execute(sql).fetchall()
                except Exception: continue
                for row in rows:
                    values = dict(row)
                    raw, court = str(values.get("text") or ""), str(values.get("court") or "")
                    case_id, title = int(values.get("id") or 0), str(values.get("title") or "")
                    sid = source_upsert(conn, "case_manager", f"case://{case_id}/{label}/{hashlib.sha1(raw.encode()).hexdigest()}", f"{label}：{title}", raw, str(values.get("updated_at") or ""), case_id, title, str(values.get("case_number") or ""))
                    count["sources"] += 1
                    for entry in case_extract(conn, raw, court):
                        count["contacts"] += int(upsert_entry(conn, sid, entry).get("ok", False))
            conn.commit()
        return count

    ensure_schema()

    @app.get("/court-directory")
    def court_directory_page():
        return FileResponse(str(frontend_dir / "court-directory.html"), headers={"Cache-Control": "no-cache"})

    @app.get("/api/court-directory/courts")
    def courts():
        with get_db() as conn:
            # 每个法院的联系方式计数：一个人员（或部门）无论几个号码都算一条；广东高院下四个中院排前，其余按默认顺序。
            direct = {}
            for r in conn.execute("""SELECT p.court_id cid, COUNT(DISTINCT p.id) n FROM court_directory_people p
                 WHERE EXISTS(SELECT 1 FROM court_directory_contacts ct WHERE ct.owner_kind='person' AND ct.owner_id=p.id) GROUP BY p.court_id"""):
                direct[r["cid"]] = direct.get(r["cid"], 0) + r["n"]
            for r in conn.execute("""SELECT d.court_id cid, COUNT(DISTINCT d.id) n FROM court_directory_departments d
                 WHERE EXISTS(SELECT 1 FROM court_directory_contacts ct WHERE ct.owner_kind='department' AND ct.owner_id=d.id) GROUP BY d.court_id"""):
                direct[r["cid"]] = direct.get(r["cid"], 0) + r["n"]
            totals: dict[int, int] = {}
            children: dict[int | None, list[int]] = {}
            for r in conn.execute("SELECT id,parent_id FROM court_directory_courts"):
                children.setdefault(r["parent_id"], []).append(int(r["id"]))

            def accumulate(node: int) -> int:
                total = direct.get(node, 0)
                for kid in children.get(node, []):
                    total += accumulate(kid)
                totals[node] = total
                return total

            for r in conn.execute("SELECT id FROM court_directory_courts WHERE parent_id IS NULL"):
                accumulate(int(r["id"]))
            items = [dict(r) for r in conn.execute("""SELECT * FROM court_directory_courts
                ORDER BY CASE WHEN name='巡回法庭' THEN 0 WHEN name='广东省高级人民法院' THEN 1 ELSE 2 END,
                parent_id,
                CASE WHEN name IN ('广州市中级人民法院','广州铁路运输中级法院','佛山市中级人民法院','深圳市中级人民法院')
                     THEN CASE name WHEN '广州市中级人民法院' THEN 0 WHEN '广州铁路运输中级法院' THEN 1 WHEN '佛山市中级人民法院' THEN 2 ELSE 3 END
                     ELSE 4 END,
                court_level, name""").fetchall()]
            for item in items:
                item["contact_count"] = totals.get(int(item["id"]), 0)
            return {"items": items}

    @app.get("/api/court-directory/filters")
    def filters(court_id: str = ""):
        cid = int(court_id) if str(court_id or "").isdigit() else 0
        with get_db() as conn:
            sql, args = "SELECT id,name FROM court_directory_departments", []
            if cid: sql += " WHERE court_id=?"; args.append(cid)
            return {"departments": [dict(r) for r in conn.execute(sql + " ORDER BY name", args).fetchall()], "positions": [r[0] for r in conn.execute("SELECT DISTINCT position FROM court_directory_affiliations WHERE position<>'' ORDER BY position").fetchall()]}

    @app.get("/api/court-directory/contacts")
    def contacts(q: str = "", court_id: str = "", department_id: str = "", position: str = "", include_history: bool = False):
        cid = int(court_id) if str(court_id or "").isdigit() else 0
        did = int(department_id) if str(department_id or "").isdigit() else 0
        with get_db() as conn:
            items, total = query_results(conn, q.strip(), cid, did, position.strip(), include_history)
            return {"items": items, "total": total}

    @app.get("/api/court-directory/people/{person_id}")
    def person_detail(person_id: int):
        with get_db() as conn:
            person = conn.execute("SELECT p.*,c.name court_name FROM court_directory_people p JOIN court_directory_courts c ON c.id=p.court_id WHERE p.id=?", (person_id,)).fetchone()
            if not person: raise HTTPException(status_code=404, detail="未找到人员")
            affiliations = [dict(r) for r in conn.execute("SELECT a.*,d.name department FROM court_directory_affiliations a LEFT JOIN court_directory_departments d ON d.id=a.department_id WHERE a.person_id=? ORDER BY a.effective_at DESC", (person_id,)).fetchall()]
            contacts = [dict(r) for r in conn.execute("SELECT ct.*,o.observed_at,o.evidence,s.source_url,s.title,s.published_at,s.collected_at,s.case_id,s.case_title,s.case_number FROM court_directory_contacts ct LEFT JOIN court_directory_contact_observations o ON o.contact_id=ct.id LEFT JOIN court_directory_sources s ON s.id=o.source_id WHERE ct.owner_kind='person' AND ct.owner_id=? ORDER BY COALESCE(s.published_at,o.observed_at,s.collected_at) DESC", (person_id,)).fetchall()]
            logs = [dict(r) for r in conn.execute("""SELECT target_kind,target_id,action,detail_json,created_at FROM court_directory_audit_logs
                WHERE (target_kind='person' AND target_id=?) OR (target_kind='contact' AND target_id IN (SELECT id FROM court_directory_contacts WHERE owner_kind='person' AND owner_id=?))
                ORDER BY created_at DESC, id DESC LIMIT 30""", (person_id, person_id)).fetchall()]
            return {"person": dict(person), "affiliations": affiliations, "contacts": contacts, "logs": logs}

    @app.get("/api/court-directory/departments/{department_id}")
    def department_detail(department_id: int):
        with get_db() as conn:
            department = conn.execute("SELECT d.*,c.name court_name FROM court_directory_departments d JOIN court_directory_courts c ON c.id=d.court_id WHERE d.id=?", (department_id,)).fetchone()
            if not department: raise HTTPException(status_code=404, detail="未找到部门")
            contacts = [dict(r) for r in conn.execute("SELECT ct.*,o.observed_at,o.evidence,s.source_url,s.title,s.published_at,s.collected_at,s.case_id,s.case_title,s.case_number FROM court_directory_contacts ct LEFT JOIN court_directory_contact_observations o ON o.contact_id=ct.id LEFT JOIN court_directory_sources s ON s.id=o.source_id WHERE ct.owner_kind='department' AND ct.owner_id=? ORDER BY COALESCE(s.published_at,o.observed_at,s.collected_at) DESC", (department_id,)).fetchall()]
            logs = [dict(r) for r in conn.execute("""SELECT target_kind,target_id,action,detail_json,created_at FROM court_directory_audit_logs
                WHERE (target_kind='department' AND target_id=?) OR (target_kind='contact' AND target_id IN (SELECT id FROM court_directory_contacts WHERE owner_kind='department' AND owner_id=?))
                ORDER BY created_at DESC, id DESC LIMIT 30""", (department_id, department_id)).fetchall()]
            return {"department": dict(department), "contacts": contacts, "logs": logs}

    @app.put("/api/court-directory/contacts/{contact_id}")
    async def update_contact(contact_id: int, request: Request):
        body = await request.json()
        phone, email = norm(body.get("phone")), norm(body.get("email"))
        if phone and not valid_phone(phone):
            raise HTTPException(status_code=400, detail="联系电话格式不正确")
        if email and not re.search(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$", email):
            raise HTTPException(status_code=400, detail="电子邮箱格式不正确")
        with get_db() as conn:
            contact = conn.execute("SELECT * FROM court_directory_contacts WHERE id=?", (contact_id,)).fetchone()
            if not contact: raise HTTPException(status_code=404, detail="未找到联系方式")
            if phone:
                duplicate = conn.execute("SELECT id FROM court_directory_contacts WHERE owner_kind=? AND owner_id=? AND normalized_phone=? AND id<>?", (contact["owner_kind"], contact["owner_id"], normalized_phone(phone), contact_id)).fetchone()
                if duplicate: raise HTTPException(status_code=400, detail="该号码已存在，无需重复添加")
            stamp = now()
            conn.execute("UPDATE court_directory_contacts SET phone=?,normalized_phone=?,email=?,updated_at=? WHERE id=?", (phone, normalized_phone(phone), email, stamp, contact_id))
            detail = json.dumps({
                "phone_before": contact["phone"], "phone_after": phone,
                "email_before": contact["email"] or "", "email_after": email,
            }, ensure_ascii=False)
            conn.execute("INSERT INTO court_directory_audit_logs(target_kind,target_id,action,detail_json,created_at) VALUES(?,?,?,?,?)", ("contact", contact_id, "manual_update", detail, stamp))
            conn.commit()
        return {"ok": True}

    @app.put("/api/court-directory/status")
    async def update_status(request: Request):
        body = await request.json(); kind, target_id = norm(body.get("target_kind")), int(body.get("target_id") or 0)
        status, note, at = norm(body.get("status")), norm(body.get("note")), norm(body.get("status_at")) or now()
        table = {"person": "court_directory_people", "contact": "court_directory_contacts"}.get(kind)
        if not table or not target_id: raise HTTPException(status_code=400, detail="修订对象无效")
        with get_db() as conn:
            conn.execute(f"UPDATE {table} SET manual_status=?,status_note=?,status_at=?,updated_at=? WHERE id=?", (status, note, at, now(), target_id))
            conn.execute("INSERT INTO court_directory_audit_logs(target_kind,target_id,action,detail_json,created_at) VALUES(?,?,?,?,?)", (kind,target_id,"manual_status",json.dumps(body,ensure_ascii=False),now())); conn.commit()
        return {"ok": True}

    @app.post("/api/court-directory/people/{person_id}/transfer")
    async def manual_transfer(person_id: int, request: Request):
        body = await request.json()
        department, position, effective_at = canonical_department(body.get("department")), norm(body.get("position")), norm(body.get("effective_at")) or now()
        if not department: raise HTTPException(status_code=400, detail="请填写调整后的部门")
        with get_db() as conn:
            person = conn.execute("SELECT court_id FROM court_directory_people WHERE id=?", (person_id,)).fetchone()
            if not person: raise HTTPException(status_code=404, detail="未找到人员")
            stamp = now()
            conn.execute("INSERT OR IGNORE INTO court_directory_departments(court_id,name,normalized_name,aliases_json,created_at,updated_at) VALUES(?,?,?,?,?,?)", (person["court_id"], department, department, "[]", stamp, stamp))
            department_id = int(conn.execute("SELECT id FROM court_directory_departments WHERE court_id=? AND normalized_name=?", (person["court_id"], department)).fetchone()[0])
            conn.execute("UPDATE court_directory_affiliations SET ended_at=?,status='transferred' WHERE person_id=? AND COALESCE(ended_at,'')=''", (effective_at, person_id))
            transfer_exists = conn.execute("SELECT id FROM court_directory_affiliations WHERE person_id=? AND department_id=? AND position=? AND source_id IS NULL", (person_id, department_id, position)).fetchone()
            if not transfer_exists:
                conn.execute("INSERT INTO court_directory_affiliations(person_id,department_id,position,status,effective_at,created_at) VALUES(?,?,?,?,?,?)", (person_id, department_id, position, "active", effective_at, stamp))
            conn.execute("INSERT INTO court_directory_audit_logs(target_kind,target_id,action,detail_json,created_at) VALUES(?,?,?,?,?)", ("person",person_id,"manual_transfer",json.dumps(body,ensure_ascii=False),stamp)); conn.commit()
        return {"ok": True, "department_id": department_id}

    @app.put("/api/court-directory/people/{person_id}/name")
    async def rename_person(person_id: int, request: Request):
        body = await request.json()
        name = norm(body.get("name"))
        if not name:
            raise HTTPException(status_code=400, detail="姓名不能为空")
        with get_db() as conn:
            person = conn.execute("SELECT * FROM court_directory_people WHERE id=?", (person_id,)).fetchone()
            if not person: raise HTTPException(status_code=404, detail="未找到人员")
            if name == person["name"]:
                return {"ok": True}
            duplicate = conn.execute("SELECT id FROM court_directory_people WHERE court_id=? AND normalized_name=? AND id<>?", (person["court_id"], name, person_id)).fetchone()
            if duplicate:
                raise HTTPException(status_code=400, detail=f"该法院下已存在同名人员「{name}」，如需更正请先处理重复记录")
            stamp = now()
            conn.execute("UPDATE court_directory_people SET name=?,normalized_name=?,updated_at=? WHERE id=?", (name, name, stamp, person_id))
            detail = json.dumps({"name_before": person["name"], "name_after": name}, ensure_ascii=False)
            conn.execute("INSERT INTO court_directory_audit_logs(target_kind,target_id,action,detail_json,created_at) VALUES(?,?,?,?,?)", ("person",person_id,"manual_rename",detail,stamp))
            conn.commit()
        return {"ok": True}

    def match_court_text(conn: Any, *texts: str) -> str:
        """按顺序在标题/正文中匹配已知法院全称；优先数据库既存法院，其次正则检测法院名。

        公众号正文常不写法院全称（标题“广州市黄埔区人民法院通讯录…”才出现），
        因此要把标题与正文一起用于归集，避免整批联系人没有法院归属。
        """
        known = conn.execute("SELECT name FROM court_directory_courts ORDER BY LENGTH(name) DESC").fetchall()
        # 先在所有文本中查找已收录的法院全称，避免“广州各法院”这类泛称抢先命中。
        for row in known:
            for text in texts:
                if str(row[0]) in text:
                    return str(row[0])
        # 其次仅接受“X人民法院”规范名，泛称不能当作法院节点。
        for text in texts:
            for name in detect_court_names(text):
                if "人民法院" in name:
                    return name
        return ""

    def preview_match(conn: Any, entry: dict[str, Any]) -> str:
        """为导入预览说明该行会如何归集，区分人员与部门号码。"""
        if not court_id(conn, norm(entry.get("court"))):
            return "新增或需补全法院"
        if norm(entry.get("name")):
            return "同法院同名归集"
        if canonical_department(entry.get("department")):
            return "同法院同部门归集"
        return "同法院归集"

    @app.post("/api/court-directory/import-preview")
    async def import_preview(request: Request):
        body = await request.json(); url, pasted = norm(body.get("url")), str(body.get("raw_text") or "").strip()
        if pasted:
            title, raw = norm(body.get("title")) or "人工粘贴的公开通讯录正文", pasted
            url = url or f"manual://pasted-public-text/{hashlib.sha256(raw.encode()).hexdigest()[:16]}"
            published_at = normalize_published(body.get("published_at"))
        else:
            if not url:
                raise HTTPException(status_code=400, detail="请粘贴公开链接，或粘贴文章正文")
            title, raw, published_at = await fetch_url(url)
        with get_db() as conn:
            default_court = norm(body.get("court"))
            if not default_court:
                default_court = match_court_text(conn, raw, title)
            entries = await extract_entries(conn, raw, default_court)
            cur = conn.execute("INSERT INTO court_directory_import_batches(url,title,raw_text,published_at,status,extraction_json,created_at) VALUES(?,?,?,?,?,?,?)", (url,title,raw[:120000],published_at,"preview",json.dumps(entries,ensure_ascii=False),now()))
            conn.commit()
            preview = [{**x, "match": preview_match(conn, x)} for x in entries]
        return {"batch_id": int(cur.lastrowid), "title": title, "entries": preview, "unrecognized": max(0, len(raw.splitlines()) - len(entries))}

    @app.post("/api/court-directory/import-image-preview")
    async def import_image_preview(file: UploadFile, court: str = ""):
        """上传/粘贴表格型法院通讯录照片，本机 OCR 识别后按同一规则分析、去重并预览。"""
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="空文件")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"} and not (file.content_type or "").startswith("image/"):
            raise HTTPException(status_code=400, detail="仅支持 PNG/JPG/JPEG/WebP/BMP/TIFF 图片")
        raw = ocr_image_bytes(data)
        if not raw.strip():
            raise HTTPException(status_code=422, detail="未能从图片识别出文字，请换用更清晰的照片、调整角度后再试，或直接粘贴正文")
        title = f"照片识别：{norm(file.filename) or '法院通讯录照片'}"
        default_court = norm(court)
        with get_db() as conn:
            if not default_court:
                default_court = match_court_text(conn, raw, title)
            entries = await extract_entries(conn, raw, default_court)
            cur = conn.execute("INSERT INTO court_directory_import_batches(url,title,raw_text,published_at,status,extraction_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (f"image-ocr://{hashlib.sha256(data).hexdigest()[:16]}", title, raw[:120000], "", "preview", json.dumps(entries, ensure_ascii=False), now()))
            conn.commit()
            preview = [{**x, "match": preview_match(conn, x)} for x in entries]
        return {"batch_id": int(cur.lastrowid), "title": title, "entries": preview, "unrecognized": max(0, len(raw.splitlines()) - len(entries)), "ocr_text": raw}

    @app.post("/api/court-directory/import-batches/{batch_id}/confirm")
    async def confirm_import(batch_id: int, request: Request):
        try: body = await request.json()
        except Exception: body = {}
        with get_db() as conn:
            batch = conn.execute("SELECT * FROM court_directory_import_batches WHERE id=?", (batch_id,)).fetchone()
            if not batch: raise HTTPException(status_code=404, detail="导入批次不存在")
            if batch["status"] == "confirmed": return {"ok": True, "imported": 0}
            sid = source_upsert(conn, "public_url", batch["url"], batch["title"], batch["raw_text"], batch["published_at"])
            raw_entries = json.loads(batch["extraction_json"] or "[]")
            edited = body.get("entries")
            if isinstance(edited, list):
                # 用户可能在预览列表里改过法院/部门/姓名/电话，逐条合并原始条目，保留未编辑字段（邮箱、依据、时间等）。
                by_idx = {i: e for i, e in enumerate(raw_entries)}
                cleaned = []
                for e in edited:
                    base = dict(by_idx.get(e.get("_i")) or {})
                    for k in ("court", "department", "name", "position", "phone"):
                        if e.get(k) is not None:
                            base[k] = e.get(k)
                    cleaned.append(base)
            else:
                cleaned = raw_entries
            imported = sum(1 for entry in cleaned if upsert_entry(conn, sid, entry).get("ok"))
            conn.execute("UPDATE court_directory_import_batches SET status='confirmed',confirmed_at=? WHERE id=?", (now(), batch_id)); conn.commit()
        return {"ok": True, "imported": imported}

    @app.post("/api/court-directory/backfill-cases")
    def backfill_case_contacts(): return {"ok": True, **backfill_cases()}

    @app.post("/api/court-directory/backfill-publish-times")
    async def backfill_publish_times():
        """为早期导入的公开来源回填文章发布时间（同一链接只抓取一次）。"""
        with get_db() as conn:
            rows = conn.execute("SELECT id,source_url FROM court_directory_sources WHERE source_kind='public_url' AND COALESCE(published_at,'')='' AND source_url LIKE 'http%'").fetchall()
        by_url: dict[str, list[int]] = {}
        for row in rows:
            by_url.setdefault(str(row["source_url"]), []).append(int(row["id"]))
        updated, failed = 0, 0
        for url, ids in by_url.items():
            try:
                _, _, published = await fetch_url(url)
                if not published:
                    failed += 1
                    continue
                with get_db() as conn:
                    conn.execute("UPDATE court_directory_sources SET published_at=? WHERE id IN (%s)" % ",".join("?" * len(ids)), [published] + ids)
                    conn.commit()
                updated += len(ids)
            except Exception:
                failed += 1
        return {"ok": True, "sources": len(rows), "updated": updated, "failed": failed}

    @app.post("/api/court-directory/discover")
    async def discover_sources(request: Request):
        body = await request.json(); query = norm(body.get("query")) or "广东省 法院 通讯录 法官 联系电话"
        try:
            # 通讯录公开来源发现只使用搜狗微信搜索，不混入通用网页或百科结果。
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 APEX Court Directory", "Referer": "https://wx.sogou.com/pcindex/"}) as client:
                response = await client.get("https://weixin.sogou.com/weixin", params={"type": 2, "s_from": "input", "ie": "utf8", "query": query})
                response.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"搜狗微信搜索暂时不可用：{exc}")
        soup = BeautifulSoup(response.text, "html.parser")
        items = []
        seen_urls = set()
        for anchor in soup.select("h3 a, .news-box h3 a, .txt-box h3 a"):
            # 搜狗微信结果使用 /link?... 形式的相对站内跳转地址，不能当作无效链接过滤。
            url = urljoin("https://weixin.sogou.com", norm(anchor.get("href")))
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc.endswith("sogou.com") or not parsed.path.startswith("/link") or url in seen_urls:
                continue
            seen_urls.add(url)
            node = anchor.find_parent(class_=re.compile(r"news-box|txt-box")) or anchor.find_parent("li")
            snippet = node.get_text(" ", strip=True) if node else ""
            items.append({"url": url, "title": anchor.get_text(" ", strip=True), "snippet": snippet[:500]})
        return {"query": query, "items": items}
