# 国家法律法规数据库 MCP 接入

法律操作系统通过国家法律法规数据库的公开检索与文档下载接口，提供实时检索、官方法规收录、版本检测、人工确认更新和回滚。

## 配置

- `NPC_LAW_DB_URL`：国家法律法规数据库基础地址，默认 `https://flk.npc.gov.cn`。
- `NATIONAL_LAW_SCHEDULER_DISABLED=1`：关闭每日只读检测（通常仅在测试时使用）。

所有国家库请求集中在 `backend/national_law_mcp.py`，页面接口发生变化时只需在此处调整。

## MCP 工具

- `search_national_laws`：按标题或全文检索，默认查询有效和尚未生效法规。
- `get_national_law_hits`：取得命中的完整法条。
- `get_national_law_detail`：取得官方元数据和 DOCX 地址。
- `check_national_law_update`：检查效力状态及同名新版本。

## 更新安全规则

- 未绑定文章只生成候选，必须逐项人工确认，不会自动建立官方对应关系。
- 检测不会改写正文；只有勾选项目并执行“更新选中项”才会更新。
- 覆盖更新保留文章 ID、笔记、收藏、置顶和自定义标签。
- 更新前保存正文和元数据快照，可通过更新记录回滚。
- 每日检测仅处理已确认绑定的法规，只生成提醒，不自动更新。
- 单项请求失败会记录在检测结果中，并继续处理其他文章。

## HTTP 接口

- `GET /api/national-laws/status`
- `POST /api/national-laws/search`
- `POST /api/national-laws/import`
- `POST /api/national-laws/update-scans`
- `GET /api/national-laws/update-scans/latest`
- `GET /api/national-laws/update-scans/{scan_id}`
- `POST /api/national-laws/update-scans/{scan_id}/confirm-matches`
- `POST /api/national-laws/update-scans/{scan_id}/apply`
- `POST /api/national-laws/updates/{update_id}/rollback`
