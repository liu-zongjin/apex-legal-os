#!/usr/bin/env python3
"""Build a data-free Apple Silicon Stella preview from a Git source allowlist."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
TEXT_SUFFIXES={'.py','.swift','.html','.js','.css'}
BRAND_ASSETS={'frontend/stella-brand.png','frontend/static/site.webmanifest'}
FORBIDDEN_PARTS={'.git','uploads','article_images','data','outputs','browser-profile','browser-profiles','__pycache__'}
SECRET_PATTERNS=[re.compile(r'(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}'),re.compile(r'(?:ghp|github_pat)_[A-Za-z0-9_]{20,}'),re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]


def allowed(path):
    p=Path(path)
    if set(p.parts)&FORBIDDEN_PARTS or p.name.startswith(('local_', '.env')): return False
    return (p.parts[0] in ('backend','frontend') and p.suffix in TEXT_SUFFIXES
            or path in BRAND_ASSETS
            or path.startswith('frontend/static/') and p.name.startswith(('app-icon-','apple-touch-icon')) and p.suffix=='.png')


def isolated_source(root,stage):
    manifest=[]
    entries=subprocess.check_output(['git','ls-tree','-rz','HEAD'],cwd=root).split(b'\0')
    for entry in entries:
        if not entry: continue
        metadata,path_bytes=entry.split(b'\t',1); mode,_,blob=metadata.split(); path=path_bytes.decode()
        if not allowed(path): continue
        if mode not in (b'100644',b'100755'): raise RuntimeError('Refusing non-regular source entry: '+path)
        content=subprocess.check_output(['git','cat-file','blob',blob.decode()],cwd=root)
        if Path(path).suffix in TEXT_SUFFIXES:
            text=content.decode('utf-8')
            if any(pattern.search(text) for pattern in SECRET_PATTERNS): raise RuntimeError('Credential pattern in source: '+path)
            # In the frozen app, the recipient's editable settings must live outside the signed bundle.
            for base in ('Path(__file__).resolve().parent.parent','Path(ai_config.__file__).resolve().parent.parent','Path(ai_config_module.__file__).resolve().parent.parent'):
                for filename in ('local_ai_secrets.py','local_ai_prefs.json'):
                    text=text.replace(f'{base} / "{filename}"',f'Path(os.environ.get("LEGAL_KB_CONFIG_DIR", str({base}))) / "{filename}"')
            if path == 'frontend/index.html':
                text = text.replace('</head>', '<link rel="stylesheet" href="/static/preview-brand.css?v=2" />\n</head>')
            content=text.encode('utf-8')
        target=stage/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(content)
        manifest.append({'path':path,'sha256':hashlib.sha256(content).hexdigest()})
    entry=root/'scripts/distribution/preview_entry.py'
    shutil.copyfile(entry,stage/'preview_entry.py')
    shutil.copyfile(root/'scripts/distribution/preview-brand.css',stage/'frontend/preview-brand.css')
    # User-authored binary document templates are never copied. Generate plain trial templates anew.
    from docx import Document
    templates=stage/'backend/archive_templates'; templates.mkdir()
    for category in ('litigation','non_litigation'):
        for kind in ('summary','catalog'):
            doc=Document(); doc.core_properties.author='Stella Preview'
            doc.add_heading('案卷归档示例模板（体验版）',0)
            doc.add_paragraph('本文件为空白体验模板，不包含任何真实案件材料。')
            if kind=='summary':
                table=doc.add_table(rows=8,cols=2)
                for row,label in zip(table.rows,['案件名称','委托人','对方当事人','案号','承办律师','收案日期','结案日期','案件摘要']):
                    row.cells[0].text=label
            else:
                table=doc.add_table(rows=1,cols=4)
                for cell,label in zip(table.rows[0].cells,['序号','材料名称','日期','备注']): cell.text=label
            doc.save(templates/f'{category}_{kind}.docx')
    (stage/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest


def build(output, keep_stage=False):
    if os.uname().machine!='arm64': raise RuntimeError('Build on an Apple Silicon Mac')
    output.mkdir(parents=True,exist_ok=True)
    workspace=Path(tempfile.mkdtemp(prefix='stella-private-preview-'))
    stage=workspace/'source'; stage.mkdir()
    manifest=isolated_source(ROOT,stage)
    app=output/'Stella Preview.app'
    if app.exists(): raise RuntimeError('Output already exists; use a new output directory')
    macos=app/'Contents/MacOS'; resources=app/'Contents/Resources'; macos.mkdir(parents=True); resources.mkdir()
    build_env=os.environ.copy()
    build_env.pop('PYTHONPATH',None)
    for key in list(build_env):
        if key.endswith(('_API_KEY','_AUTH_CODE','_AUTHORIZATION','_WEB_COOKIE','_ACCESS_TOKEN')): build_env.pop(key,None)
    command=[shutil.which('python3'),'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','stella-preview-server',
        '--distpath',str(workspace/'frozen'),'--workpath',str(workspace/'work'),'--specpath',str(workspace),
        '--paths',str(stage),'--add-data',f'{stage}/frontend:frontend', '--add-data',f'{stage}/backend:backend',
        '--collect-submodules','backend','--collect-all','jieba', '--hidden-import','uvicorn.logging',
        '--hidden-import','uvicorn.loops.auto','--hidden-import','uvicorn.protocols.http.auto','--hidden-import','uvicorn.lifespan.on',
        '--exclude-module','torch','--exclude-module','tensorflow','--exclude-module','matplotlib',
        '--exclude-module','scipy','--exclude-module','onnxruntime','--exclude-module','ddddocr','--exclude-module','tkinter',
        str(stage/'preview_entry.py')]
    subprocess.run(command,cwd=stage,env=build_env,check=True)
    frozen=workspace/'frozen/stella-preview-server'
    shutil.copytree(frozen,resources/'Server')
    swift=ROOT/'native-shell/Sources/main.swift'
    native_source=workspace/'preview-native.swift'
    native_source.write_text(swift.read_text().replace(':8000',':18865'))
    subprocess.run(['xcrun','swiftc','-O','-whole-module-optimization','-target','arm64-apple-macosx11.3',
                    '-framework','Cocoa','-framework','WebKit','-framework','LocalAuthentication',
                    '-framework','EventKit','-framework','UserNotifications',str(native_source),'-o',str(macos/'StellaNative')],check=True)
    subprocess.run(['xcrun','swiftc','-O','-target','arm64-apple-macosx11.3','-framework','EventKit',
                    str(ROOT/'backend/calendar_bridge.swift'),'-o',str(macos/'APEXCalendarBridge')],check=True)
    info=plistlib.loads((ROOT/'native-shell/Info.plist').read_bytes())
    info.update(CFBundleIdentifier='com.stella.preview.native',CFBundleDisplayName='Stella Preview',CFBundleName='Stella Preview',
                CFBundleExecutable='StellaPreview',LegalKBFrontendPath='',CFBundleShortVersionString='1.0.0',CFBundleVersion='1')
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    shutil.copyfile(ROOT/'native-shell/StellaIcon.png',resources/'StellaBrand.png')
    icon=ROOT/'dist/Stella.app/Contents/Resources/AppIcon.icns'
    if icon.exists(): shutil.copyfile(icon,resources/'AppIcon.icns')
    # Strip caller environment; every runtime path belongs to the new preview on the recipient's Mac.
    launcher=macos/'StellaPreview'
    launcher.write_text('''#!/bin/bash
set -euo pipefail
APP_CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="$HOME/Library/Application Support/StellaPreview"
mkdir -p "$RUNTIME"
if /usr/bin/nc -z 127.0.0.1 18865 2>/dev/null; then
  /usr/bin/osascript -e 'display dialog "Stella Preview 的专用端口已被占用。请先退出旧的体验版后重试。" buttons {"知道了"}'
  exit 1
fi
/usr/bin/env -i HOME="$HOME" PATH="/usr/bin:/bin:/usr/sbin:/sbin" TMPDIR="${TMPDIR:-/tmp}" LANG="zh_CN.UTF-8" \\
  "$APP_CONTENTS/Resources/Server/stella-preview-server" --runtime "$RUNTIME" >> "$RUNTIME/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM
for i in $(seq 1 120); do
  if /usr/bin/curl --silent --fail http://127.0.0.1:18865/api/server-status >/dev/null; then break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then exit 1; fi
  sleep 1
done
"$APP_CONTENTS/MacOS/StellaNative"
''')
    launcher.chmod(0o755)
    subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
    subprocess.run([str(resources/'Server/stella-preview-server'),'--runtime',str(workspace/'validation-runtime'),'--self-test'],
                   cwd=workspace,env=build_env,check=True)
    audit_bundle(app)
    readme=output/'使用说明.txt'
    readme.write_text('''Stella 私密体验版（Apple 芯片 Mac，macOS 11.3 或更新）

1. 解压，将 Stella Preview.app 拖到“应用程序”或您自己的 Applications 文件夹。
2. 打开应用即可使用，无需安装 Python，无需 GitHub 账号。
3. 软件没有开发者公证。若 macOS 提示无法验证开发者，请按系统设置 → 隐私与安全性中的官方“仍要打开”流程确认来源；不要关闭系统安全保护。
4. 第一次启动自动生成两个虚构案件、三篇全新编写的示例文章、少量联系人、待办和演示日程。个人财务为空。
5. AI API、MCP、Skills 管理页保留；所有密钥和账号配置为空，请填写您自己的信息。团队通用默认律师资料保留。
6. 体验数据独立保存在 ~/Library/Application Support/StellaPreview，退出应用会关闭随包后端。
7. 本包不含开发者的数据库、案件附件、上传文件、个人财务、AI聊天/长期记忆、API/MCP密钥、邮箱授权码、浏览器会话或钥匙串导出。
8. 自动读取司法短信已默认关闭。法院登录、邮箱、AI、MCP等联网服务须自行配置；部分浏览器自动化/本地验证码功能需要另行安装可选运行环境。
9. 仅供获得分享者授权的团队成员内部体验，请勿公开转载、上传公共仓库或转发提取码。
''',encoding='utf-8')
    report={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'source_files':len(manifest),'architecture':'arm64','runtime_data_included':False,
            'credentials_included':False,'fictional_data_created_on_first_run':True}
    (output/'包装检查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    archive=output/'Stella-Private-Preview-AppleSilicon-v2.zip'
    subprocess.run(['ditto','-c','-k','--norsrc','--noextattr','--keepParent',str(app),str(archive)],check=True)
    import zipfile
    with zipfile.ZipFile(archive,'a',compression=zipfile.ZIP_DEFLATED) as z:
        z.write(readme,readme.name); z.write(output/'包装检查.json','包装检查.json')
    (output/'SHA256.txt').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    print('PACKAGE_READY',archive)
    if not keep_stage: shutil.rmtree(workspace)
    return archive


def audit_bundle(app):
    for path in app.rglob('*'):
        if not path.is_file(): continue
        relative=path.relative_to(app)
        public_ca_bundle = path.name == 'cacert.pem' and path.parent.name == 'certifi'
        if (path.suffix in ('.db','.sqlite','.sqlite3','.pem','.key','.p12') and not public_ca_bundle) or path.name.startswith(('local_', '.env')):
            raise RuntimeError('Runtime/private file in bundle: '+str(relative))
        own_source = 'backend' in relative.parts or 'frontend' in relative.parts
        if own_source and set(relative.parts)&FORBIDDEN_PARTS:
            raise RuntimeError('User data directory in bundle: '+str(relative))
        if path.suffix in TEXT_SUFFIXES and any(p.search(path.read_text(errors='ignore')) for p in SECRET_PATTERNS):
            raise RuntimeError('Credential pattern in bundle: '+str(relative))


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--keep-stage',action='store_true')
    args=parser.parse_args(); build(args.output.resolve(),args.keep_stage)
