# 图片链接显示问题修复

## 问题描述
用户报告文章正文中的图片超链接无法点击、点击无法正常显示图片。

## 根本原因
在 `legal-kb/frontend/app.js` 的 `renderBodyContent` 函数中，第132行的代码存在问题：

```javascript
return `<p>${escapeHtml(processedContent)}</p>`;
```

这段代码对整个 `processedContent` 进行了 HTML 转义，但 `processedContent` 已经包含了图片链接的 HTML 标签（如 `<a href="..." ...>`），导致：
- HTML 标签被转义成纯文本（例如 `<` 变成 `&lt;`）
- 图片链接无法渲染为可点击的链接
- 用户只能看到转义后的 HTML 代码

## 修复方案
使用 `split()` 方法按图片标记分割内容，然后：
1. 对**非图片标记的文本部分**进行 HTML 转义（防止 XSS 攻击）
2. 对**图片 URL 部分**生成可点击的 HTML 链接
3. 重新组合所有部分

### 修复后的代码
```javascript
// 普通段落：块内各行合并（段内换行用空格连接）
// 处理段落中的图片链接
// 使用 split 和 replace 的组合来安全地处理图片标记和HTML转义
const content = lines.join('');

// 将内容按图片标记分割，对非标记部分进行转义，然后重新组合
const parts = content.split(IMAGE_RE);
const processedContent = parts.map((part, index) => {
  // 奇数索引是图片URL，偶数索引是普通文本
  if (index % 2 === 1 && part && part.startsWith('http')) {
    // 这是一个图片URL
    return `<a href="${escapeHtml(part)}" target="_blank" class="image-link" onclick="event.stopPropagation(); showImagePreview('${escapeHtml(part)}'); return false;">📷 查看图片</a>`;
  } else {
    // 这是普通文本，需要转义HTML
    return escapeHtml(part || '');
  }
}).join('');

return `<p>${processedContent}</p>`;
```

## 修复效果
- ✅ 图片标记 `[图片: URL]` 正确转换为可点击的链接
- ✅ 点击链接可以在预览窗口中查看图片
- ✅ 普通文本中的 HTML 特殊字符被正确转义，防止 XSS 攻击
- ✅ 支持同一段落中包含多个图片链接
- ✅ 独立的图片块（单独一行的图片标记）也能正常显示

## 版本更新
- `legal-kb/frontend/index.html`: 将 `app.js` 版本号从 `v=10` 更新到 `v=11`，确保浏览器加载最新代码

## 测试验证
已通过以下测试验证修复效果：
1. 单个图片标记的处理
2. 多个图片标记在同一段落中的处理
3. HTML 特殊字符的转义功能（`<script>` 等标签被正确转义）
4. 独立图片块的处理

所有测试均通过，图片链接可以正常点击和显示。
