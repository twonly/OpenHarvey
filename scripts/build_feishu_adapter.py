"""Build the private host credential helper from the official pinned source."""
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.76'

def main():
    target = ROOT/'output/feishu-adapter-build'
    target.mkdir(parents=True, exist_ok=True)
    raw = urllib.request.urlopen(f'https://codeload.github.com/larksuite/cli/tar.gz/refs/tags/v{VERSION}', timeout=60).read()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        archive.extractall(target, filter='data')
    source = target/f'cli-{VERSION}'
    entry = source/'cmd/workbench-credentials'
    entry.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/'deploy/feishu/credential_adapter.go', entry/'main.go')
    binary = ROOT/'output/feishu-credential-adapter'
    subprocess.run(['go','build','-trimpath','-o',str(binary),'./cmd/workbench-credentials'], cwd=source, check=True)
    binary.chmod(0o700)
    (target/'source.sha256').write_text(hashlib.sha256(raw).hexdigest()+'\n')
    print(binary)

if __name__ == '__main__': main()
