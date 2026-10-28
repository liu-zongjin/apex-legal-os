"use strict";
const $ = (id) => document.getElementById(id);
const articleId = Number(
  new URLSearchParams(location.search).get("article_id"),
);
let book,
  operations = [],
  selected = { row: 1, col: 1 },
  busy = false,
  inputDirty = false;
function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}
async function request(url, options) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) throw Error(data.detail || "操作失败");
  return data;
}
function column(n) {
  let out = "";
  while (n) {
    n--;
    out = String.fromCharCode(65 + (n % 26)) + out;
    n = Math.floor(n / 26);
  }
  return out;
}
function coordinate(raw) {
  const m = /^([A-Z]{1,3})([1-9]\d{0,6})$/.exec(raw.trim().toUpperCase());
  if (!m) throw Error("请输入有效坐标，例如 A1");
  let c = 0;
  for (const ch of m[1]) c = c * 26 + ch.charCodeAt(0) - 64;
  const r = Number(m[2]);
  if (c > 16384 || r > 1048576) throw Error("坐标超出表格范围");
  return { row: r, col: c };
}
function range() {
  const parts = $("area").value.trim().split(":");
  if (parts.length > 2) throw Error("选区格式无效");
  const a = coordinate(parts[0]),
    b = coordinate(parts[1] || parts[0]);
  if (
    a.row > b.row ||
    a.col > b.col ||
    (b.row - a.row + 1) * (b.col - a.col + 1) > 10000
  )
    throw Error("选区应按左上至右下填写，最多 10000 格");
  return { a, b, text: column(a.col) + a.row + ":" + column(b.col) + b.row };
}
function change(op) {
  if (!book || busy) throw Error("请等待表格加载完成");
  if (book.protected && op.kind !== "add_sheet") throw Error("该工作表受保护");
  if (operations.length >= 2000) throw Error("请先保存当前修改");
  operations.push({ ...op, sheet: book.sheet });
  notice(`有 ${operations.length} 项修改尚未保存`);
}
function capture() {
  if (!inputDirty) return;
  const raw = $("value").value;
  let value = raw,
    literal = false;
  if (raw.startsWith("'")) {
    value = raw.slice(1);
    literal = true;
  } else if (raw.trim() === "") value = null;
  else if (
    /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(raw) &&
    Number.isFinite(Number(raw)) &&
    raw.replace(/[-.]/g, "").length <= 15
  )
    value = Number(raw);
  if (raw.length > 32767) throw Error("单元格最多 32767 字符");
  change({ kind: "cell", ...selected, value, literal });
  const item = book.cells[selected.row - book.row]?.[selected.col - book.col];
  if (item) {
    item.value = value;
    item.text = value === null ? "" : String(value);
    item.formula =
      !literal && typeof value === "string" && value.startsWith("=");
  }
  inputDirty = false;
  renderGrid();
}
function pick(row, col, extend = false) {
  capture();
  const item = book.cells[row - book.row][col - book.col];
  if (item.merged) {
    notice("此处属于合并单元格，请选择左上角单元格", true);
    return;
  }
  const previous = selected;
  selected = { row, col };
  $("address").textContent = column(col) + row;
  $("value").value = item.value === null ? "" : String(item.value);
  $("area").value = extend
    ? column(Math.min(previous.col, col)) +
      Math.min(previous.row, row) +
      ":" +
      column(Math.max(previous.col, col)) +
      Math.max(previous.row, row)
    : column(col) + row;
  renderGrid();
}
function renderGrid() {
  const grid = $("grid");
  grid.replaceChildren();
  const cols = document.createElement("colgroup");
  cols.append(document.createElement("col"));
  book.widths.forEach((width) => {
    const el = document.createElement("col");
    el.style.width = Math.max(40, width * 7 + 8) + "px";
    cols.append(el);
  });
  grid.append(cols);
  const head = grid.createTHead().insertRow();
  head.append(document.createElement("th"));
  book.widths.forEach((_, i) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = column(book.col + i);
    head.append(th);
  });
  const tbody = grid.createTBody();
  const merges = book.merges.map((raw) => {
    const parts = raw.split(":");
    return { a: coordinate(parts[0]), b: coordinate(parts[1] || parts[0]) };
  });
  book.cells.forEach((line, i) => {
    const tr = tbody.insertRow(),
      r = book.row + i;
    tr.style.height = (book.heights[i] * 96) / 72 + "px";
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = r;
    tr.append(th);
    line.forEach((item, j) => {
      const c = book.col + j;
      const merge = merges.find(
        (m) => r >= m.a.row && r <= m.b.row && c >= m.a.col && c <= m.b.col,
      );
      if (
        merge &&
        (r !== Math.max(merge.a.row, book.row) ||
          c !== Math.max(merge.a.col, book.col))
      )
        return;
      const td = tr.insertCell();
      if (merge) {
        td.rowSpan = Math.min(merge.b.row, book.row + 49) - r + 1;
        td.colSpan = Math.min(merge.b.col, book.col + 19) - c + 1;
      }
      td.textContent = item.text;
      td.title = item.text;
      td.tabIndex = selected.row === r && selected.col === c ? 0 : -1;
      td.dataset.row = r;
      td.dataset.col = c;
      td.dataset.merged = item.merged;
      td.classList.toggle("selected", selected.row === r && selected.col === c);
      td.style.fontWeight = item.bold ? "700" : "400";
      if (item.font_size)
        td.style.fontSize = Math.max(8, Math.min(72, item.font_size)) + "pt";
      if (/^#[a-f0-9]{6}$/i.test(item.font_color || ""))
        td.style.color =
          ["#000000", "#ffffff"].includes(item.font_color.toLowerCase()) &&
          !item.fill
            ? "var(--sheet-text)"
            : item.font_color;
      if (/^#[a-f0-9]{6}$/i.test(item.fill || ""))
        td.style.backgroundColor = item.fill;
      td.style.whiteSpace = item.wrap ? "pre-wrap" : "pre";
      if (["left", "right", "center", "justify"].includes(item.align))
        td.style.textAlign = item.align;
      for (const [side, style] of Object.entries(item.borders)) {
        if (style) {
          td.style["border" + side[0].toUpperCase() + side.slice(1)] =
            `${style === "medium" ? 2 : 1}px ${style === "dashed" || style === "dotted" ? style : "solid"} var(--sheet-text)`;
        }
      }
      td.addEventListener("click", (e) => safe(() => pick(r, c, e.shiftKey)));
      td.addEventListener("dblclick", () => {
        $("value").focus();
        $("value").select();
      });
      td.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          $("value").focus();
          return;
        }
        const delta = {
          ArrowDown: [1, 0],
          ArrowUp: [-1, 0],
          ArrowLeft: [0, -1],
          ArrowRight: [0, 1],
          Tab: [0, e.shiftKey ? -1 : 1],
        }[e.key];
        if (delta) {
          e.preventDefault();
          const nr = r + delta[0],
            nc = c + delta[1];
          if (
            nr >= book.row &&
            nr < book.row + 50 &&
            nc >= book.col &&
            nc < book.col + 20
          ) {
            safe(() => pick(nr, nc));
            grid
              .querySelector(`td[data-row="${nr}"][data-col="${nc}"]`)
              ?.focus();
          }
        }
      });
    });
  });
}
function render() {
  const nav = $("sheets");
  nav.replaceChildren();
  book.sheets.forEach((name) => {
    const b = document.createElement("button");
    b.textContent = name;
    b.className = name === book.sheet ? "active" : "";
    b.setAttribute("aria-pressed", name === book.sheet);
    b.onclick = () => safe(() => load(name, 1, 1));
    nav.append(b);
  });
  $("title").textContent = book.title;
  $("position").textContent =
    `${book.sheet} · ${column(book.col)}${book.row} 起，每页 50 行 × 20 列`;
  $("prev").disabled = book.row <= 1;
  $("left").disabled = book.col <= 1;
  $("export").href = `/api/articles/${articleId}/spreadsheet/export`;
  renderGrid();
}
async function load(sheet = "", row = 1, col = 1) {
  if (busy) return;
  if (operations.length || inputDirty) {
    notice("请先保存修改，再切换工作表、翻页或重新载入", true);
    return;
  }
  busy = true;
  try {
    const data = await request(
      `/api/articles/${articleId}/spreadsheet?` +
        new URLSearchParams({ sheet, row, col }),
    );
    book = data;
    selected = { row: data.row, col: data.col };
    render();
    $("address").textContent = column(selected.col) + selected.row;
    $("area").value = $("address").textContent;
    $("value").value = book.cells[0][0].value ?? "";
    notice(
      book.legacy
        ? "旧版 XLS：保存时转为 XLSX，仅保留单元格值；原格式与公式请使用 Excel 转换后再导入。"
        : book.protected
          ? "工作表受保护，仅供查看。"
          : "已载入。可选择单元格，或填写区域批量调整边框。",
    );
  } finally {
    busy = false;
  }
}
async function save() {
  if (busy) return;
  capture();
  if (!operations.length) {
    notice("没有需要保存的修改");
    return;
  }
  busy = true;
  $("save").disabled = true;
  const sheet = book.sheet,
    row = book.row,
    col = book.col;
  try {
    const data = await request(`/api/articles/${articleId}/spreadsheet`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision: book.revision, operations }),
    });
    operations = [];
    inputDirty = false;
    book.revision = data.revision;
    parent.postMessage(
      { type: "apex:article-workbook-saved", articleId, content: data.content },
      location.origin,
    );
    busy = false;
    await load(sheet, row, col);
    notice("已保存。原始文件保持完整，导出可获取编辑后的副本。");
  } finally {
    busy = false;
    $("save").disabled = false;
  }
}
async function safe(fn) {
  try {
    await fn();
  } catch (e) {
    notice(e.message || "操作失败", true);
  }
}
function format(values) {
  capture();
  const area = range();
  change({ kind: "format", range: area.text, ...values });
  for (let r = area.a.row; r <= area.b.row; r++)
    for (let c = area.a.col; c <= area.b.col; c++) {
      const item = book.cells[r - book.row]?.[c - book.col];
      if (!item) continue;
      if ("bold" in values) item.bold = values.bold;
      if ("wrap" in values) item.wrap = values.wrap;
      if ("border" in values)
        for (const side of ["left", "right", "top", "bottom"])
          item.borders[side] =
            values.border === "none"
              ? null
              : values.border === "outer"
                ? {
                    left: c === area.a.col,
                    right: c === area.b.col,
                    top: r === area.a.row,
                    bottom: r === area.b.row,
                  }[side]
                  ? "thin"
                  : null
                : values.border;
    }
  renderGrid();
}
$("value").addEventListener("input", () => (inputDirty = true));
$("value").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    safe(capture);
  }
});
$("apply").onclick = () => safe(capture);
$("save").onclick = () => safe(save);
$("reload").onclick = () => safe(() => load(book?.sheet, book?.row, book?.col));
$("prev").onclick = () =>
  safe(() => load(book.sheet, Math.max(1, book.row - 50), book.col));
$("next").onclick = () =>
  safe(() => load(book.sheet, Math.min(1048527, book.row + 50), book.col));
$("left").onclick = () =>
  safe(() => load(book.sheet, book.row, Math.max(1, book.col - 20)));
$("right").onclick = () =>
  safe(() => load(book.sheet, book.row, Math.min(16365, book.col + 20)));
$("go").onclick = () =>
  safe(() => {
    const at = coordinate($("jump").value);
    return load(book.sheet, at.row, at.col);
  });
$("add-sheet").onclick = () =>
  safe(() => {
    capture();
    const name = $("sheet-name").value.trim();
    if (
      !name ||
      name.length > 31 ||
      /[\[\]:*?/\\]/.test(name) ||
      book.sheets.some((n) => n.toLowerCase() === name.toLowerCase())
    )
      throw Error("请输入有效且不重复的工作表名称");
    change({ kind: "add_sheet", name });
    notice("新表已加入草稿，保存后可切换。");
  });
$("formats")
  .querySelectorAll("[data-border]")
  .forEach(
    (button) =>
      (button.onclick = () =>
        safe(() => format({ border: button.dataset.border }))),
  );
$("bold").onclick = () => safe(() => format({ bold: true }));
$("normal").onclick = () => safe(() => format({ bold: false }));
$("wrap").onclick = () => safe(() => format({ wrap: true }));
$("set-height").onclick = () =>
  safe(() => {
    capture();
    const area = range(),
      value = Number($("height").value);
    if (!Number.isFinite(value) || value < 8 || value > 300)
      throw Error("行高应在 8 至 300 磅之间");
    if (area.b.row - area.a.row > 1000) throw Error("一次最多调整 1000 行");
    for (let r = area.a.row; r <= area.b.row; r++) {
      change({ kind: "row_height", row: r, value });
      if (r >= book.row && r < book.row + 50)
        book.heights[r - book.row] = value;
    }
    renderGrid();
  });
$("set-width").onclick = () =>
  safe(() => {
    capture();
    const area = range(),
      value = Number($("width").value);
    if (!Number.isFinite(value) || value < 3 || value > 100)
      throw Error("列宽应在 3 至 100 之间");
    for (let c = area.a.col; c <= area.b.col; c++) {
      change({ kind: "column_width", col: c, value });
      if (c >= book.col && c < book.col + 20) book.widths[c - book.col] = value;
    }
    renderGrid();
  });
window.ApexWorkbook = {
  hasChanges: () => busy || operations.length > 0 || inputDirty,
};
let discardArmed = false;
$("discard").onclick = () =>
  safe(async () => {
    if (busy) return;
    if (!discardArmed) {
      discardArmed = true;
      $("discard").textContent = "再次点击确认放弃";
      notice("将放弃本次未保存的修改，已保存的文件不受影响");
      return;
    }
    operations = [];
    inputDirty = false;
    discardArmed = false;
    $("discard").textContent = "放弃草稿";
    await load(book?.sheet, book?.row, book?.col);
  });
$("draft").onclick = () => {
  const data = {
    articleId,
    revision: book?.revision,
    operations,
    pendingInput: inputDirty ? { ...selected, value: $("value").value } : null,
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "电子表格编辑草稿.json";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
try {
  const syncTheme = () => {
    const style = parent.getComputedStyle(parent.document.body);
    for (const key of [
      "--bg-card",
      "--bg-secondary",
      "--text",
      "--text-secondary",
      "--border",
      "--accent",
    ]) {
      const value = style.getPropertyValue(key);
      if (value.trim()) document.documentElement.style.setProperty(key, value);
    }
  };
  syncTheme();
  const themeObserver = new MutationObserver(syncTheme);
  themeObserver.observe(parent.document.documentElement, {
    attributes: true,
    attributeFilter: ["class", "style", "data-theme"],
  });
  themeObserver.observe(parent.document.body, {
    attributes: true,
    attributeFilter: ["class", "style", "data-theme"],
  });
  window.addEventListener("pagehide", () => themeObserver.disconnect());
} catch (_) {
  /* Standalone viewer uses its own theme. */
}
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    safe(save);
  }
});
safe(() => load());
