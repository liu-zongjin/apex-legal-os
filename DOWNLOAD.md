# 下载与安装

作者：刘宗锦律师

## 一键下载源码

[点击下载完整源码 ZIP](https://github.com/liu-zongjin/apex-legal-os/archive/refs/heads/main.zip)

仓库公开后，无需 GitHub 账号即可下载。也可在仓库首页点击 **Code → Download ZIP**。解压后进入 `apex-legal-os-main` 目录。

该下载是源码包，需要自行安装运行环境。当前未提供已公证的桌面安装包；不要将源码 ZIP 当作可直接打开的 Mac 应用。

## 在 macOS 运行

安装 Python 3 与 Node.js 后，在解压目录的终端中执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-private.txt
npm ci
python3 start.py
```

启动后访问 http://localhost:8000 。部分功能需要自行配置 AI、邮件或其他第三方服务的账号；macOS 系统集成功能还需要系统权限。浏览器自动化等可选功能可能需要额外运行环境。

下载包不包含作者的案件数据库、案件附件、账号密钥或私人浏览器会话。首次运行由程序创建本机数据；请配置自己的账号。

## Git 下载

```bash
git clone https://github.com/liu-zongjin/apex-legal-os.git
cd apex-legal-os
```

## 使用范围

**禁止商用、禁止修改；作者：刘宗锦律师。** 运行未修改的源码、安装依赖和填写设置按 [LICENSE](LICENSE) 允许的范围进行。用于律所商业运营、收费法律服务或修改代码，须取得作者书面授权。转发时请附许可协议、署名和原项目地址。
