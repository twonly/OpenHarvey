#!/usr/bin/env python3
"""Sandbox-side consistent idle backup and bounded log reads. No credentials."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tarfile
import tempfile

ARCHIVE=Path('/tmp/contract-checkpoint.tar.gz')
ROOTS=['workspace','var/lib/contract-opencode/data','var/lib/contract-opencode/state']


def backup(base=Path("/"), archive=ARCHIVE):
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp)
        for root in ROOTS:
            source=base/root
            if not source.exists():continue
            for p in source.rglob('*'):
                if not p.is_file() or p.is_symlink():continue
                if p.name in {'auth.json','.publish-token'} or p.name.endswith(('-wal','-shm')):continue
                dest=stage/root/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True)
                with p.open('rb') as f:header=f.read(16)
                if header==b'SQLite format 3\x00':
                    with sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True) as src,sqlite3.connect(dest) as target:src.backup(target)
                else:shutil.copyfile(p,dest)
        with tarfile.open(archive,'w:gz') as tar:
            for p in stage.iterdir():tar.add(p,arcname=p.name)


def restore(base=Path("/"), archive=ARCHIVE):
    with tarfile.open(archive,'r:gz') as tar:
        members=tar.getmembers()
        for m in members:
            p=Path(m.name)
            if p.is_absolute() or '..' in p.parts or m.issym() or m.islnk() or not (m.isfile() or m.isdir()):raise ValueError('Invalid checkpoint entry')
            if not any(m.name==r or m.name.startswith(r+'/') or r.startswith(m.name+'/') for r in ROOTS):raise ValueError('Invalid checkpoint root')
        tar.extractall(base,members=members,filter='data')
    # Restored files must be writable by the same account running OpenCode.
    import subprocess
    if base==Path('/'):
        subprocess.run(['chown','-R','user:user','/workspace','/var/lib/contract-opencode'],check=True)


def log(offset):
    p=Path('/var/log/contract-opencode/service.log')
    if not p.exists():print(json.dumps({'offset':0,'text':''}));return
    if offset>p.stat().st_size:offset=0
    with p.open('rb') as f:
        f.seek(offset);data=f.read(128*1024);offset=f.tell()
    print(json.dumps({'offset':offset,'text':data.decode('utf-8',errors='replace')}))


if __name__=='__main__':
    if sys.argv[1]=='backup':backup()
    elif sys.argv[1]=='restore':restore()
    elif sys.argv[1]=='log':log(int(sys.argv[2]))
    else:raise ValueError('Unknown operation')
