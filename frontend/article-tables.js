/* Article-body table controls reuse the existing editor selection and save flow. */
let articleTableRange = null;
function openArticleTableTools() {
  _restoreBodyEditorSelection();
  const selection = window.getSelection();
  articleTableRange = selection?.rangeCount
    ? selection.getRangeAt(0).cloneRange()
    : null;
  let panel = document.getElementById("article-table-tools");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "article-table-tools";
    panel.className = "article-table-tools";
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-label", "正文表格设置");
    panel.innerHTML = `<label>行数<input id="article-table-rows" type="number" min="1" max="100" value="3"></label><label>列数<input id="article-table-cols" type="number" min="1" max="20" value="3"></label><button type="button" data-table-action="insert">添加表格</button><label>行高（像素）<input id="article-table-height" type="number" min="20" max="300" value="36"></label><label>文字行距<input id="article-table-spacing" type="number" min="1" max="3" step="0.1" value="1.5"></label><button type="button" data-table-action="size">应用行高与行距</button><span>边框</span><button type="button" data-table-action="thin">细线</button><button type="button" data-table-action="medium">粗线</button><button type="button" data-table-action="dashed">虚线</button><button type="button" data-table-action="none">无边框</button><button type="button" data-table-action="row">添加行</button><button type="button" data-table-action="col">添加列</button><button type="button" data-table-action="close">收起</button><span class="article-table-help">点击表格中的单元格，再应用设置。修改后点击正文编辑器的保存。</span>`;
    document.querySelector("#edit-body-modal .format-toolbar")?.append(panel);
    if (!panel.isConnected)
      document.getElementById("body-editor")?.parentElement.before(panel);
    panel.addEventListener("mousedown", (event) => {
      if (event.target.closest("button")) event.preventDefault();
    });
    panel.addEventListener("click", (event) => {
      const button = event.target.closest("[data-table-action]");
      if (button) applyArticleTableAction(button.dataset.tableAction);
    });
  }
  panel.hidden = false;
}
function applyArticleTableAction(action) {
  const editor = document.getElementById("body-editor"),
    panel = document.getElementById("article-table-tools");
  if (action === "close") {
    panel.hidden = true;
    return;
  }
  const selection = window.getSelection();
  const live = selection?.rangeCount ? selection.getRangeAt(0) : null;
  if (live && editor.contains(live.commonAncestorContainer))
    articleTableRange = live.cloneRange();
  if (
    articleTableRange &&
    editor.contains(articleTableRange.commonAncestorContainer)
  ) {
    editor.focus({ preventScroll: true });
    selection.removeAllRanges();
    selection.addRange(articleTableRange);
  } else {
    _restoreBodyEditorSelection();
  }
  const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
  if (!range || !editor.contains(range.commonAncestorContainer)) {
    showToast("请先在正文中选择插入位置或单元格");
    return;
  }
  const node =
    range.startContainer.nodeType === 1
      ? range.startContainer
      : range.startContainer.parentElement;
  let table = node.closest("table");
  function number(id, min, max) {
    const value = Number(document.getElementById(id).value);
    if (!Number.isFinite(value) || value < min || value > max)
      throw Error("请输入范围内的有效尺寸");
    return value;
  }
  try {
    if (action === "insert") {
      if (table) throw Error("请在现有表格外选择插入位置");
      const rows = number("article-table-rows", 1, 100),
        cols = number("article-table-cols", 1, 20);
      if (!Number.isInteger(rows) || !Number.isInteger(cols))
        throw Error("行数和列数须为整数");
      table = document.createElement("table");
      table.style.cssText =
        "border-collapse:collapse;width:100%;table-layout:fixed";
      const body = table.createTBody();
      for (let r = 0; r < rows; r++) {
        const tr = body.insertRow();
        for (let c = 0; c < cols; c++) {
          const cell = tr.insertCell();
          cell.style.cssText =
            "border:1px solid #808080;padding:6px 8px;line-height:1.5;vertical-align:top";
          cell.append(document.createElement("br"));
        }
      }
      // Insert at a block boundary; avoid invalid nested tables inside paragraphs.
      let block = node;
      while (block.parentElement !== editor && block.parentElement)
        block = block.parentElement;
      if (block === editor) {
        range.deleteContents();
        range.insertNode(table);
      } else block.after(table);
      const after = document.createElement("p");
      after.append(document.createElement("br"));
      table.after(after);
      range.selectNodeContents(table.rows[0].cells[0]);
      range.collapse(true);
    } else {
      if (!table || !editor.contains(table))
        throw Error("请先点击要调整的表格单元格");
      if (action === "size") {
        const height = number("article-table-height", 20, 300),
          spacing = number("article-table-spacing", 1, 3);
        [...table.rows].forEach((row) => {
          row.style.height = height + "px";
          [...row.cells].forEach((cell) => {
            cell.style.height = height + "px";
            cell.style.lineHeight = String(spacing);
            cell
              .querySelectorAll("p,div")
              .forEach((p) => (p.style.lineHeight = String(spacing)));
          });
        });
      } else if (["thin", "medium", "dashed", "none"].includes(action)) {
        const border =
          action === "none"
            ? "none"
            : `${action === "medium" ? 2 : 1}px ${action === "dashed" ? "dashed" : "solid"} #808080`;
        table.style.borderCollapse = "collapse";
        table.style.border = border;
        table
          .querySelectorAll("td,th")
          .forEach((cell) => (cell.style.border = border));
      } else if (action === "row") {
        if (table.rows.length >= 100) throw Error("正文表格最多 100 行");
        const source = node.closest("tr") || table.rows[table.rows.length - 1],
          row = source.cloneNode(true);
        row
          .querySelectorAll("td,th")
          .forEach((cell) =>
            cell.replaceChildren(document.createElement("br")),
          );
        source.after(row);
      } else if (action === "col") {
        if ([...table.rows].some((row) => row.cells.length >= 20))
          throw Error("正文表格最多 20 列");
        if (table.querySelector("[colspan],[rowspan]"))
          throw Error("合并单元格表格请使用 Excel 编辑列结构");
        [...table.rows].forEach((row) => {
          const cell = row.insertCell();
          cell.style.cssText = row.cells[0]?.style.cssText || "";
          cell.append(document.createElement("br"));
        });
      }
    }
    selection.removeAllRanges();
    selection.addRange(range);
    articleTableRange = range.cloneRange();
    _bodyEditorSavedRange = range.cloneRange();
    _onBodyEditorInput();
  } catch (error) {
    showToast(error.message);
  }
}
window.addEventListener("message", (event) => {
  if (
    event.origin !== location.origin ||
    event.data?.type !== "apex:article-workbook-saved"
  )
    return;
  const frame = [
    ...document.querySelectorAll("iframe.article-workbook-frame"),
  ].find((item) => item.contentWindow === event.source);
  if (
    !frame ||
    Number(frame.dataset.articleId) !== Number(event.data.articleId) ||
    typeof event.data.content !== "string"
  )
    return;
  for (const tab of tabState.tabs) {
    if (
      Number(tab.data?.articleId) === Number(event.data.articleId) &&
      tab.data.article
    ) {
      tab.data.article.content = event.data.content;
      const indexedBody = document.getElementById(`tab-detail-body-${tab.id}`);
      if (indexedBody?.hidden) indexedBody.textContent = event.data.content;
    }
  }
  if (Number(state.currentArticle?.id) === Number(event.data.articleId))
    state.currentArticle.content = event.data.content;
});
