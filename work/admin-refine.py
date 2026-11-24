"""Historical admin editing script for the matching pre-redesign source tree."""
from pathlib import Path

if '历史渠道 · 安装包点击' in Path('services/public-admin/public/index.html').read_text():
    raise SystemExit('The admin redesign is already applied.')
base=Path('services/public-admin')
p=base/'src/worker.js';s=p.read_text().replace("WHEN os LIKE 'Windows %' THEN 'windows' ELSE 'unknown'", "WHEN os LIKE 'Windows %' THEN 'windows' WHEN channel='source' AND version='2026110501' AND os GLOB '[1-9]*.[0-9]*.[0-9]*' THEN 'mac' ELSE 'unknown'");p.write_text(s)
p=base/'public/index.html';s=p.read_text().replace('归档 · GitHub 仓库流量快照','辅助参考 · GitHub 仓库流量').replace('GitHub 源码仓库历史','GitHub 源码仓库流量').replace('快照仅在同步时变化；','每 10 分钟尝试同步，失败保留上次结果；表格保留已同步日历史，顶部总数仅对应最近快照窗口，不是历史累计；').replace('纯数字系统版本无法独立证明平台，保留未知。','源码协议 2026110501 的非零数字系统值来自 mac_ver，归为 macOS；其他无依据记录保留未知。').replace('设备最近一次保存的构建版本，最多延迟六小时','累计已上报安装标识按最近保存值分组，最多展示 50 组；源码协议号不代表产品版本，最多延迟六小时');
# Prioritize ongoing usage before auxiliary repository traffic.
a=s.index('<details class="panel archive"><summary>辅助参考');b=s.index('</details>',a)+len('</details>');block=s[a:b];s=s[:a]+s[b:];where=s.index('<details class="panel archive"><summary>归档');s=s[:where]+block+s[where:];p.write_text(s)
p=base/'public/navigation.js';s=p.read_text().replace('.cards,.panel,.panels,.analytics-grid,footer','.cards,.panel,.panels,.analytics-grid,footer').replace('section.scrollIntoView({','if(section.tagName===\'DETAILS\')section.open=true;section.scrollIntoView({');p.write_text(s)
