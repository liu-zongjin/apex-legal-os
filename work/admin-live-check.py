import os
from urllib.parse import urlsplit

import requests
base=os.environ.get('STELLA_ADMIN_URL','').rstrip('/')
target=urlsplit(base)
password=os.environ.get('STELLA_ADMIN_PASSWORD')
if target.scheme != 'https' or not target.netloc or not password:
 raise SystemExit('Set STELLA_ADMIN_URL (HTTPS) and STELLA_ADMIN_PASSWORD')
s=requests.Session()
r=s.post(base+'/api/login',json={'password':password},headers={'Origin':base},timeout=25)
print('Login:',r.status_code);r.raise_for_status()
for path in ['/','/navigation.js','/admin.css','/api/summary','/api/website?days=30&device=all','/api/source-traffic']:
 r=s.get(base+path,timeout=25);print(path,r.status_code);r.raise_for_status()
 if path=='/':
  html=r.content.decode('utf-8');print('New navigation asset:', '/navigation.js' in html);assert '/navigation.js' in html and '兼容口径 · UTC 每日记录' in html
 if path=='/api/summary':
  data=r.json();assert 'systems' in data;assert sum(row['count'] for row in data['systems'])==data['active_month'];print('System breakdown:',data['systems'])
print('Production checks passed')
