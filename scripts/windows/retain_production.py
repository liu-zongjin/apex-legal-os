"""Retain split clean production artifacts on an orphan private CI branch for SSH.

No private signing key or runtime profile is ever placed in this transport.
"""
import hashlib,json,os,subprocess,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def git(*args,data=None):
 return subprocess.check_output(['git',*args],cwd=ROOT,input=data).decode().strip()
def blob(data):return git('hash-object','-w','--stdin',data=data)
def main():
 output=ROOT/'build/windows-production'
 verification=json.loads((output/'FULL-INSTALL-VERIFICATION.json').read_text())
 assert verification['pass']
 entries=[]
 with tempfile.TemporaryDirectory(prefix='stella-production-transport-') as directory:
  archive=Path(directory)/'components.tar'
  with tarfile.open(archive,'w') as target:
   for path in sorted(output.iterdir()):
    assert path.suffix in ('.zip','.json'),path
    target.add(path,arcname=path.name,recursive=False)
   installers=list((ROOT/'windows-installer/src-tauri/target/release/bundle/nsis').glob('*.exe'))
   assert len(installers)==1
   target.add(installers[0],arcname='Stella-Windows-1.1.5-setup.exe',recursive=False)
  parts=[]
  with archive.open('rb') as source:
   while True:
    data=source.read(40*1024*1024)
    if not data:break
    name='part-'+str(len(parts)).zfill(3)
    parts.append({'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    entries.append('100644 blob '+blob(data)+'\t'+name)
  manifest={'source':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'parts':parts,
            'archive_bytes':archive.stat().st_size,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
  entries.append('100644 blob '+blob(json.dumps(manifest,indent=2).encode())+'\tmanifest.json')
  tree=git('mktree',data=('\n'.join(sorted(entries))+'\n').encode())
  commit=git('-c','user.name=Stella CI','-c','user.email=ci@example.invalid','commit-tree',tree,data=b'Verified clean Windows production artifacts\n')
  subprocess.run(['git','-c','pack.window=0','-c','pack.compression=0','push','origin',
      commit+':refs/heads/ci/windows-production-artifacts-'+os.environ['GITHUB_RUN_ID']],cwd=ROOT,check=True)
 print('PRODUCTION_CANDIDATES_RETAINED_FOR_LOCAL_SIGNING')
if __name__=='__main__':main()
