"""Capture owner-authorized GitHub traffic. Never treat clones as active users."""
import datetime
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def main():
    data = {kind: json.loads(subprocess.check_output(
        ['gh', 'api', 'repos/liu-zongjin/apex-legal-os/traffic/' + kind], text=True))
        for kind in ('clones', 'views')}
    stamps = [row['timestamp'][:10] for kind in data for row in data[kind][kind]]
    payload = {'repository': 'liu-zongjin/apex-legal-os',
               'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'start': min(stamps), 'end': max(stamps), **data}
    target = ROOT / 'services/public-admin/public/source-traffic.json'
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print('Saved GitHub traffic snapshot; clone count:', data['clones']['count'])

if __name__ == '__main__':
    main()
