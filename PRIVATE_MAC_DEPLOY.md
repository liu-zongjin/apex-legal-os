# 闲置 Mac 私有部署说明

## 1. 准备闲置 Mac

1. 接上电源并联网。
2. 安装 Tailscale，并用你的个人账号登录。
3. 在 Tailscale 管理后台开启 MagicDNS，建议把这台设备命名为 `legal-kb-mac`。
4. 在 Tailscale 管理后台的 `DNS` 页面开启 `HTTPS Certificates`。首次安装时也可按安装脚本提示授权开启。
5. 系统设置中关闭自动睡眠，或至少设置为接通电源时不睡眠。

## 2. 复制知识库

把整个 `legal-kb` 文件夹复制到闲置 Mac。建议放在用户主目录，例如：

```text
~/legal-kb
```

不要放在 `Documents`、`Desktop`、`Downloads` 或 iCloud Drive 里；这些目录受 macOS 隐私权限保护，后台自启动服务可能无法访问。

需要保留：

- `legal_kb.db`
- `uploads/`
- `backend/`
- `frontend/`
- `requirements-private.txt`
- `scripts/`

## 3. 安装私有服务

在闲置 Mac 的终端执行：

```bash
cd /path/to/legal-kb
bash scripts/install_private_mac.sh
```

脚本会完成：

- 安装 Python 依赖；
- 创建 `.env.private` 私有配置；
- 创建开机自启服务；
- 创建每日数据库备份任务；
- 启动知识库。
- 将知识库限制为仅本机监听，并由 Tailscale Serve 提供私有 HTTPS 入口。

## 4. 访问地址

在已经登录同一 Tailscale 账号的设备上访问安装脚本最后打印的 HTTPS 地址，例如：

```text
https://legal-kb-mac.your-tailnet.ts.net
```

必须使用完整的 `*.ts.net` 地址；短 MagicDNS 名称和 `http://IP:8000` 都不是安全来源，移动浏览器不会为它们启用 Service Worker，因此无法可靠地离线打开。

首次在手机上打开后，停留至页面显示“已缓存”。此后电脑暂时关机时，手机仍可打开已缓存页面和已同步的离线快照；在线检索、新数据和登录校验不可用。

## 5. 备份

默认备份目录：

```text
~/LegalKBBackups
```

备份策略：

- 每天备份 `legal_kb.db`；
- 每周日备份 `uploads/`；
- 数据库备份默认保留 14 天；
- 上传文件压缩包默认保留 60 天。

可以随时手动备份：

```bash
cd /path/to/legal-kb
bash scripts/backup_private.sh
```

## 6. 运维命令

查看服务状态：

```bash
launchctl print gui/$(id -u)/com.liuzongjin.legalkb.private
```

重启服务：

```bash
launchctl kickstart -k gui/$(id -u)/com.liuzongjin.legalkb.private
```

源码一致性规则：

- 私有服务会监视后端、前端和启动配置源码；保存后自动重启并重新加载最新代码。
- `/api/server-status` 同时返回运行版本和磁盘版本；只有两者一致才算服务正常。
- 发现源码变化但服务尚未完成重启时，业务接口会暂时返回 503，不会继续执行旧代码。
- `restart.py` 只有在检测到新进程且源码版本一致后才返回成功。

查看日志：

```bash
tail -f logs/private-server.log
```

诊断远程访问问题：

```bash
bash scripts/diagnose_private_mac.sh
```

停止服务：

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.liuzongjin.legalkb.private.plist
```

## 7. 私有模式行为

私有模式会：

- 要求浏览器输入用户名和密码；
- 禁用打开服务器本机文件；
- 禁用本机路径导入；
- 禁用远程清理存储/日志；
- 禁用通过网页启动新服务器进程；
- 隐藏服务器本地目录路径。

## 8. 启用司法短信智能收件箱

司法短信不是通过第三方 iCloud API 获取，而是读取这台 Mac 上“信息”已同步的本地数据库。

1. iPhone 与 Mac 使用同一 Apple 账户；iPhone“设置 → App → 信息 → 发送与接收”中必须能看到并勾选手机号。
2. Mac“信息 → 设置 → iMessage”中勾选手机号与邮箱，启用“iCloud 云端信息”，点击“现在同步”。
3. 在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”中，添加安装脚本或诊断脚本显示的 `full disk access target`。Apple Command Line Tools Python 3.8 应直接使用并授权其真实解释器 `Versions/3.8/bin/python3.8`，不要使用 `/usr/bin/python3` 启动垫片。
4. 重启服务并执行：

```bash
bash scripts/diagnose_private_mac.sh
```

诊断结果中的 `Judicial Messages` 应显示 `status: readable`。网页“案件管理 → 司法短信”还会显示数据库更新时间、最近扫描结果和 AI 配置状态。正式服务器应常接电并保持联网；若 Mac 进入睡眠，定时扫描也会暂停。

## 9. 从常用电脑一键发布更新

建议把闲置 Mac 当作正式运行环境，数据库和上传文件以闲置 Mac 为准；常用电脑只同步代码和界面更新。

第一次使用前，在闲置 Mac 打开 `系统设置 -> 通用 -> 共享`，开启 `远程登录`，允许你的用户通过 SSH 登录。

常用电脑修改并测试完成后，在常用电脑执行：

```bash
cd /path/to/legal-kb
bash scripts/deploy_to_private_mac.sh
```

默认发布到：

```text
anmeilin@legal-kb-mac:/Users/anmeilin/legal-kb
```

发布脚本会自动：

- 通过 SSH 连接闲置 Mac；
- 先运行一次远程数据库备份；
- 同步代码、前端、脚本和依赖清单；
- 排除 `legal_kb.db`、`uploads/`、`.env.private`、日志和本地密钥；
- 安装新增依赖；
- 重启知识库服务；
- 检查该 Mac 的 Tailscale HTTPS 地址的 `/api/server-status`。

如果设备名或路径不同，可以临时指定：

```bash
LEGAL_KB_DEPLOY_HOST=100.83.85.112 \
LEGAL_KB_DEPLOY_USER=anmeilin \
LEGAL_KB_DEPLOY_DIR=/Users/anmeilin/legal-kb \
bash scripts/deploy_to_private_mac.sh
```
