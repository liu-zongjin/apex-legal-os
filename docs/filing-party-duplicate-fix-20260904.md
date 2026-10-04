# 官网材料页“下一步”重复当事人修复

## 已核实的触发链

2026-09-04 直接读取人民法院在线服务网公开前端：
- 入口 `/zxfw/static/js/index.9c7b817f.js`。
- 材料页 `/zxfw/static/js/pagesWsla-common-wsla-components-file-upload-index.dd40e6aa.js`。
- 当事人页 `/zxfw/static/js/pagesWsla-common-wsla-components-ajxx-index.023a0fa3.js`。

材料页 `nextStep()` 每次调用 `GET /api/v3/layy/ocr`（普通下一步不传 operate；文本转换传 ysht），成功且 data 非空后回读 layyxq、写入 sessionStorage.layyInfo，再进入案件信息页。非空识别文本显示用户截图中的识别提示。只有上传文件 sfzxzz 标识等特定分支跳过识别；不能为了跳过识别伪造材料来源。

旧 Stella 在 API 阶段及提交前复核清理重复卡，发生在用户后来点击下一步之前，不能保护后续写入。旧复核还将有姓名但无证件号的重复卡从计数中排除。此前仅按请求方法认定 GET 可重试的代码也会重放有写入副作用的 OCR。

## 本次处理

`court_filing_ocr.py` 在 Stella 管理的法院 BrowserContext 层处理该精确 OCR 路由（包括该上下文新标签页）。只处理本地登记且 API 流程完成的待提交草稿；按草稿串行执行：读取原当事人 → 原样执行官网 OCR（不重试、不重定向）→ 回读、清理有明确匹配证据的重复卡 → 验证删除及原编号保留 → 释放原官网响应。官网随后读取去重结果。失败不重新放行原请求，不让页面带着未核验结果进入下一页。

保留原有有证件号的当事人编号；同名不同诉讼角色、证件冲突、同名多人的歧义、无证件且地址冲突以及被代理关系引用的卡均不自动删除。新增且不匹配的当事人保留。若官网返回空 data 且已清理重复卡，要求重新打开草稿，防止官网空结果分支复用过期页面缓存。

Token API OCR 单次超时提高到官网使用的 90 秒，并取消其 GET 自动重试。复核真实计入所有有姓名的卡。删除卡编号不再误用草稿编号；原清理函数补上相同诉讼角色限制。

## 验证与限制

`python3 -m unittest tests.test_court_filing_ocr tests.test_automated_filing`：34 项通过。涵盖三类角色、连续/并发请求、关系保留、删除回读失败、超时不重放、未登记草稿不处理、API 执行中不并发 OCR、身份歧义保护。

扩大到 test_court_online_service 共 52 项时有 3 项既有失败；将本次修改前模块加载后，三项仍以相同断言失败（账号作用域迁移和案件计数），未扩大修改这些无关功能。

Stella 服务已重新加载，接口健康，当前立案任务仍显示 7/7 完成。本次未创建/提交真实法院案件，未修改真实草稿。截图草稿编号的官方回读返回“记录不存在”，当前本地任务已是另一份草稿。机器锁屏，真实官网点击与截图验收未完成。

保护仅在 Stella 管理的法院浏览器上下文建立后生效，独立外部浏览器不受此代码控制；旧页面需要通过 Stella 重新打开。不能把上述模拟测试表述为官网全流程已验收，也不能声称改变了法院服务器的 OCR 实现。

## Follow-up: task 60

The OCR guard ran twice (6 and 3 removals), but the screenshot still showed an incomplete organisation whose name AND address omitted the same uncommon character. The current server read had 4 rows. Installation failure is therefore not the working explanation.

Added a narrow organisation match requiring the same role and representative, a single-character name edit, and either identical addresses or the identical single-character edit in the address. Conflicting documents, house numbers, representatives, roles, and ambiguous matches are preserved.

The browser detail-response route now reconciles and delivers verified dsrs to the page, preserving all other response fields and refreshed token headers. Stale copies require positive identity evidence; unknown manual rows are never silently filtered. Changed response lengths and compression headers are recalculated and old response caching disabled.

37 related tests pass, including the screenshot-specific omission in both fields and stale browser response versus clean server data. Live browser re-entry remains unverified; backend counts are not sufficient UI acceptance evidence.
