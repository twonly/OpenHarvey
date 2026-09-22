"""Versioned DOCX working copies. Original sources never change.

The editor lease prevents background writes while a browser has unsaved work.
File versions and operation receipts are committed together under SQLite CAS.
"""
import asyncio
import hashlib
import io
import difflib
from collections import Counter
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import signal
import tempfile
import time
import zipfile
from xml.etree import ElementTree as ET

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from .store import digest

ROOT = Path(__file__).resolve().parents[1]
MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
LOG = logging.getLogger(__name__)
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def validate_docx(data, *, clean=False):
    if len(data) > 20_000_000:
        raise HTTPException(413, 'DOCX 超过 20 MB')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(x.file_size for x in z.infolist()) > 150_000_000:
                raise ValueError('DOCX 解压后过大')
            names = z.namelist()
            if len(names) != len(set(names)) or 'word/document.xml' not in names:
                raise ValueError('DOCX 文件结构无效')
            if any('vbaproject' in n.lower() for n in names):
                raise ValueError('审改不支持宏文档')
            for name in names:
                if name.endswith(('.xml', '.rels')):
                    content = z.read(name)
                    if b'<!DOCTYPE' in content or b'<!ENTITY' in content:
                        raise ValueError('DOCX XML 结构不支持')
                    root = ET.fromstring(content)
                    if clean and name.startswith('word/') and any(e.tag in {W+'ins', W+'del', W+'moveFrom', W+'moveTo', W+'comment', W+'commentReference', W+'commentRangeStart'} or e.tag.endswith('PrChange') for e in root.iter()):
                        raise ValueError('导出仍包含修订或批注，未发布清洁版')
    except (zipfile.BadZipFile, ET.ParseError, KeyError):
        raise ValueError('DOCX 文件无法读取') from None


def same_docx_content(before, after):
    """Ignore ZIP container timestamps/compression, preserve every document part."""
    if before == after:
        return True
    with zipfile.ZipFile(io.BytesIO(before)) as a, zipfile.ZipFile(io.BytesIO(after)) as b:
        an={n for n in a.namelist() if not n.endswith('/')}
        bn={n for n in b.namelist() if not n.endswith('/')}
        return an==bn and all(a.read(n)==b.read(n) for n in an)


def check_preserved_structures(before, after):
    """Reject known structural loss on engine-only operations, not user edits."""
    def shape(data):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root=ET.fromstring(z.read('word/document.xml'))
            tags={W+x for x in ('tbl','tr','tc','sectPr','drawing','footnoteReference','endnoteReference','fldChar','object','altChunk')}
            counts=Counter(e.tag for e in root.iter() if e.tag in tags)
            images=sorted(hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('word/media/') and not n.endswith('/'))
            margins=sorted(''.join(ET.fromstring(z.read(n)).itertext()) for n in z.namelist() if n.startswith(('word/header','word/footer')) and n.endswith('.xml'))
            return counts,images,margins
    if shape(before)!=shape(after):
        raise ValueError('文档引擎改变了表格、图片、页眉页脚或域结构，未保存此结果；请下载原件处理')


def version_activity(body, before, after):
    """Describe observed operations without generating document facts with a model."""
    action=body.get('action','initial');details={}
    kind={'initial':'initial','restore':'restore','apply':'agent' if body.get('agent') else 'change',
          'decide':'review','comment':'comment','discussion':'comment'}.get(action,'edit')
    events=body.get('review_events',[])
    if action=='decide':events=[{'decision':body.get('decision'),'ids':body.get('ids',[])}]
    if events:
        kind='review'
        for decision in ('accept','reject'):
            ids={i for e in events if e.get('decision')==decision for i in e.get('ids',[])}
            if ids:details[decision]=len(ids)
        title='，'.join(f'{label} {details[key]} 处修订' for key,label in [('accept','接受'),('reject','拒绝')] if details.get(key)) or '处理合同修订'
    elif action=='restore':title='恢复历史版本'
    elif action=='initial':title='创建工作副本'
    elif action in ('comment','discussion'):
        title={'create':'添加批注','reply':'回复批注','resolve':'解决批注','delete':'删除批注'}.get(body.get('operation'),'更新批注')
    elif action=='apply':title=f'{"Agent " if body.get("agent") else ""}修改 {len(body.get("changes",[]))} 处内容'
    else:
        previous={c['id']:c for c in before.get('comments',[])};current={c['id']:c for c in after.get('comments',[])}
        added=len(current.keys()-previous.keys());removed=len(previous.keys()-current.keys())
        updated=sum(any(current[k].get(f)!=previous[k].get(f) for f in ('text','status','parentCommentId','anchoredText')) for k in current.keys()&previous.keys())
        parts=[]
        if before.get('text')!=after.get('text'):parts.append('编辑合同正文')
        if added:parts.append(f'新增 {added} 条批注或回复')
        if updated:parts.append(f'更新 {updated} 条批注')
        if removed:parts.append(f'删除 {removed} 条批注')
        title='，'.join(parts) or '更新格式或文档内容'
    return kind,body.get('summary') or title,details


class Redline:
    capabilities={'text_view':'visible','tracked_paragraph_merge':False,'tracked_paragraph_split':False,'saved_version_download':True,'automatic_request_id':True}

    def __init__(self, store):
        self.store = store
        self.locks = {}
        self.handoff_locks = {}
        self.engine_slots = asyncio.Semaphore(2)
        with store.connect() as db:
            migrate_history=not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='redline_version_meta'").fetchone()
            migrate_discussions=not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='redline_discussions'").fetchone()
            db.executescript('''
              CREATE TABLE IF NOT EXISTS redline_documents (
                document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
                version_id TEXT NOT NULL, lease_id TEXT, lease_until REAL,
                lease_thread TEXT, yield_requested INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS redline_versions (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                parent_id TEXT, hash TEXT NOT NULL, author TEXT NOT NULL,
                created REAL NOT NULL, summary TEXT NOT NULL, snapshot TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS redline_version_meta (
                version_id TEXT PRIMARY KEY REFERENCES redline_versions(id) ON DELETE CASCADE,
                kind TEXT NOT NULL DEFAULT 'legacy', thread_id TEXT, actor_id TEXT,
                details TEXT NOT NULL DEFAULT '{}', label TEXT NOT NULL DEFAULT '', label_revision INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS redline_discussions (
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                comment_id TEXT NOT NULL, version_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(document_id,comment_id));
              CREATE TABLE IF NOT EXISTS redline_operations (
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                request_id TEXT NOT NULL, request_hash TEXT NOT NULL, receipt TEXT NOT NULL,
                thread_id TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(document_id, request_id));
            ''')
            if migrate_history:
                # Backfill only from durable receipts; unknown legacy operations remain separate.
                receipts={}
                for op in db.execute('SELECT document_id,thread_id,receipt FROM redline_operations ORDER BY created').fetchall():
                    receipt=json.loads(op['receipt'])
                    if receipt.get('parent_id') and receipt.get('version_id'):
                        receipts[(op['document_id'],receipt['version_id'],receipt['parent_id'])]=(receipt,op['thread_id'])
                for v in db.execute('SELECT v.*,d.user_id FROM redline_versions v JOIN documents d ON d.id=v.document_id').fetchall():
                    receipt,tid=receipts.get((v['document_id'],v['id'],v['parent_id']),({},None))
                    action='initial' if not v['parent_id'] else 'legacy'
                    if receipt.get('author_email'):action='apply'
                    elif v['summary']=='恢复历史版本':action='restore'
                    elif receipt and (v['summary']=='用户编辑' or receipt.get('review_events')):action='save'
                    kind,_,details=version_activity({**receipt,'action':action,'agent':bool(receipt.get('author_email'))},{},{})
                    if action=='legacy':kind='legacy'
                    db.execute('INSERT INTO redline_version_meta(version_id,kind,thread_id,actor_id,details) VALUES(?,?,?,?,?)',
                               (v['id'],kind,tid,v['user_id'],json.dumps(details)))
            if migrate_discussions:
                for v in db.execute('SELECT document_id,id,snapshot FROM redline_versions ORDER BY created').fetchall():
                    self.remember_comments(db,v['document_id'],v['id'],json.loads(v['snapshot']))

    @staticmethod
    def remember_comments(db,did,vid,snapshot):
        for c in snapshot.get('comments',[]):
            db.execute('INSERT OR REPLACE INTO redline_discussions VALUES(?,?,?,?)',(did,c['id'],vid,json.dumps(c,ensure_ascii=False)))

    def enabled(self, user):
        user=self.store.one('SELECT * FROM users WHERE id=?',(user['id'],)) or user
        allowed = [name.strip() for name in os.environ.get('CW_REDLINE_USERS', '').split(',')]
        return user.get('account_kind') != 'demo' and (user['username'] in allowed or '*' in allowed)

    def authorize(self, u, t, did):
        if not self.enabled(u):
            raise HTTPException(403, '此账号尚未启用 DOCX 审改')
        # Deliberately enforce thread attachment isolation for both runtimes.
        d = self.store.one('SELECT * FROM documents WHERE id=? AND user_id=? AND workspace_id=? AND (thread_id IS NULL OR thread_id=?)', (did, u['id'], t['workspace_id'], t['id']))
        if not d:
            raise HTTPException(404, '文档不属于当前对话')
        if d['suffix'] != '.docx':
            raise HTTPException(422, '原生修订仅支持 DOCX；此文件可继续分析或生成建议稿')
        return d

    def directory(self, d):
        return self.store.user_root(d['user_id']) / 'sources' / d['id'] / 'redline'

    def version(self, d, vid=None):
        current = self.store.one('SELECT * FROM redline_documents WHERE document_id=?', (d['id'],))
        row = self.store.one('SELECT * FROM redline_versions WHERE document_id=? AND id=?', (d['id'], vid or (current or {}).get('version_id')))
        if not row:
            raise HTTPException(404, '工作版本不存在')
        return row

    def file(self, d, vid=None):
        v = self.version(d, vid)
        p = self.directory(d) / (v['id']+'.docx')
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != v['hash']:
            raise HTTPException(410, '工作版本文件缺失或损坏，请恢复备份')
        return p

    async def engine(self, source, action='inspect', **kwargs):
        started = time.monotonic()
        async with self.engine_slots:
            p = await asyncio.create_subprocess_exec(os.environ.get('CW_NODE', 'node'), str(ROOT/'scripts/superdoc-engine.mjs'), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
            try:
                stdout, stderr = await asyncio.wait_for(p.communicate(json.dumps({'source':str(source), 'action':action, **kwargs}, ensure_ascii=False).encode()), 90)
            except BaseException:
                try: os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                await p.wait()
                raise
        LOG.info('redline.engine action=%s duration=%.2f exit=%s', action, time.monotonic()-started, p.returncode)
        try: result = json.loads(stdout)
        except ValueError: raise RuntimeError('文档引擎未返回有效结果；请检查安装与服务日志') from None
        if not result.get('ok'):
            raise ValueError(result.get('error', '文档引擎操作失败'))
        return result

    async def ensure(self, d, u):
        if self.store.one('SELECT 1 FROM redline_documents WHERE document_id=?', (d['id'],)):
            return
        async with self.locks.setdefault(d['id'], asyncio.Lock()):
            if self.store.one('SELECT 1 FROM redline_documents WHERE document_id=?', (d['id'],)):
                return
            source = self.directory(d).parent/'source.docx'
            data = source.read_bytes(); validate_docx(data)
            # Import-only success is insufficient: check a disposable round-trip
            # before exposing editing for structures this engine would discard.
            with tempfile.TemporaryDirectory(prefix='redline-preflight-') as tmp:
                out=Path(tmp)/'probe.docx'
                snapshot=await self.engine(source,output=str(out))
                check_preserved_structures(data,out.read_bytes())
            self.commit(d, u, data, snapshot, '创建工作副本', None)

    def commit(self, d, u, data, snapshot, summary, parent, operation=None, discussion=None):
        validate_docx(data)
        vid, now = secrets.token_hex(12), time.time()
        root = self.directory(d); root.mkdir(parents=True, exist_ok=True)
        dest = root/(vid+'.docx'); temp = root/(vid+'.tmp')
        h = hashlib.sha256(data).hexdigest()
        receipt = {'saved':True, 'document_id':d['id'], 'version_id':vid, 'parent_id':parent, 'hash':h, 'summary':summary}
        if operation:
            receipt['download_url']=f"/api/redline/{d['id']}/file?thread_id={operation[1]['id']}&version_id={vid}"
            receipt['pending_changes']=len(snapshot.get('changes',[]))
            before=json.loads(self.version(d,parent)['snapshot'])['text'] if parent else ''
            receipt['diff']='\n'.join(difflib.unified_diff(before.splitlines(),snapshot['text'].splitlines(),fromfile=parent or 'original',tofile=vid,lineterm=''))
            receipt['operation_id'] = operation[0]['request_id']
            receipt['changes'] = operation[0].get('changes', [])
            receipt['author_email']=('agent+'+operation[0]['request_id']+'@workbench.local') if operation[0].get('agent') else None
            receipt['review_events']=operation[0].get('review_events',[])
            receipt['decision'] = operation[0].get('decision')
            receipt['revision_ids'] = operation[0].get('ids', [])
        try:
            with temp.open('wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            temp.replace(dest)
            directory_fd=os.open(root,os.O_RDONLY)
            try:os.fsync(directory_fd)
            finally:os.close(directory_fd)
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT version_id FROM redline_documents WHERE document_id=?', (d['id'],)).fetchone()
                if (row['version_id'] if row else None) != parent:
                    raise HTTPException(409, '合同已更新，请重新读取当前版本')
                db.execute('INSERT INTO redline_versions VALUES(?,?,?,?,?,?,?,?)', (vid,d['id'],parent,h,u['username'],now,summary,json.dumps(snapshot,ensure_ascii=False)))
                if row: db.execute('UPDATE redline_documents SET version_id=? WHERE document_id=?', (vid,d['id']))
                else: db.execute('INSERT INTO redline_documents(document_id,version_id) VALUES(?,?)', (d['id'],vid))
                body,thread=operation if operation else ({'action':'initial'},{})
                before=json.loads(self.version(d,parent)['snapshot']) if parent else {}
                kind,_,details=version_activity(body,before,snapshot)
                db.execute('INSERT INTO redline_version_meta(version_id,kind,thread_id,actor_id,details) VALUES(?,?,?,?,?)',
                           (vid,kind,thread.get('id'),u['id'],json.dumps(details)))
                self.remember_comments(db,d['id'],vid,snapshot)
                if discussion:
                    db.execute('UPDATE redline_discussions SET payload=? WHERE document_id=? AND comment_id=?',(json.dumps(discussion,ensure_ascii=False),d['id'],discussion['id']))
                if operation:
                    body, thread = operation
                    db.execute('INSERT INTO redline_operations VALUES(?,?,?,?,?,?)', (d['id'],body['request_id'],digest(json.dumps(body,sort_keys=True,ensure_ascii=False)),json.dumps(receipt),thread['id'],now))
                db.execute('UPDATE workspaces SET last_activity_at=? WHERE id=?', (now,d['workspace_id']))
        except BaseException:
            temp.unlink(missing_ok=True); dest.unlink(missing_ok=True); raise
        return receipt

    def state(self, d):
        v=self.version(d); result=json.loads(v.pop('snapshot'))
        versions=self.store.all('''SELECT v.id,v.parent_id,v.author,v.created,v.summary,
            COALESCE(m.kind,'legacy') AS kind,m.thread_id,m.actor_id,COALESCE(m.details,'{}') AS details,
            COALESCE(m.label,'') AS label,COALESCE(m.label_revision,0) AS label_revision
            FROM redline_versions v LEFT JOIN redline_version_meta m ON m.version_id=v.id
            WHERE v.document_id=? ORDER BY v.created DESC,v.rowid DESC''', (d['id'],))
        for item in versions:item['details']=json.loads(item['details'])
        ops=self.store.all('SELECT receipt FROM redline_operations WHERE document_id=? ORDER BY created DESC LIMIT 50', (d['id'],))
        native_ids={c['id'] for c in result.get('comments',[])}
        detached=[{**json.loads(c['payload']),'last_version':c['version_id']} for c in self.store.all('SELECT * FROM redline_discussions WHERE document_id=?',(d['id'],)) if c['comment_id'] not in native_ids]
        return {'detached_comments':detached,'ok':True,'document_id':d['id'],'filename':d['filename'],'version':v,'snapshot':result,'versions':versions,'operations':[json.loads(x['receipt']) for x in ops]}

    def label_version(self,d,vid,body):
        if not isinstance(body,dict) or not isinstance(body.get('label'),str) or type(body.get('revision')) is not int:
            raise HTTPException(422,'请填写版本名称及当前标记版本')
        label=body['label'].strip()
        if len(label)>80:raise HTTPException(422,'版本名称最多 80 个字')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM redline_versions WHERE document_id=? AND id=?',(d['id'],vid)).fetchone():
                raise HTTPException(404,'此版本不属于当前合同')
            db.execute('INSERT OR IGNORE INTO redline_version_meta(version_id) VALUES(?)',(vid,))
            current=db.execute('SELECT label,label_revision FROM redline_version_meta WHERE version_id=?',(vid,)).fetchone()
            if current['label_revision']!=body['revision']:
                # An uncertain retry of the same name is harmless; different edits conflict.
                if current['label']==label:return {'version_id':vid,'label':label,'label_revision':current['label_revision']}
                raise HTTPException(409,'版本名称已更新，请刷新版本记录后重试')
            revision=current['label_revision']+(current['label']!=label)
            db.execute('UPDATE redline_version_meta SET label=?,label_revision=? WHERE version_id=?',(label,revision,vid))
        return {'version_id':vid,'label':label,'label_revision':revision}

    def lease(self, d, t, body):
        now=time.time(); client=body.get('client_id')
        if not isinstance(client,str) or not 8<=len(client)<=80: raise ValueError('编辑会话无效')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM redline_documents WHERE document_id=?',(d['id'],)).fetchone()
            held=row['lease_id'] and row['lease_until']>now
            if held and (row['lease_id']!=client or row['lease_thread']!=t['id']):
                raise HTTPException(409,'此合同正在另一个编辑窗口中打开，请先关闭该窗口')
            if body.get('release'):
                if held: db.execute('UPDATE redline_documents SET lease_id=NULL,lease_until=NULL,lease_thread=NULL WHERE document_id=?',(d['id'],))
            else:
                # A pending agent waits for a save-and-release acknowledgement.
                if row['yield_requested'] and not held: raise HTTPException(409,'Agent 正在写入修订，请稍候')
                db.execute('UPDATE redline_documents SET lease_id=?,lease_until=?,lease_thread=? WHERE document_id=?',(client,now+30,t['id'],d['id']))
            return {'version_id':row['version_id'],'yield_requested':bool(row['yield_requested']), 'expires':now+30}

    async def apply(self, u, t, body, *, data=None):
        if not isinstance(body,dict):raise ValueError('文档操作必须为 JSON 对象')
        did=body.get('document_id'); d=self.authorize(u,t,did); await self.ensure(d,u)
        action=body.get('action','inspect')
        if action=='inspect':
            state=self.state(d)
            if not body.get('history'):
                state.pop('versions',None);state.pop('operations',None)
            state['capabilities']=dict(self.capabilities)
            return state
        if action=='diff':
            before=self.version(d,body.get('before_version'));after=self.version(d,body.get('after_version'))
            a=json.loads(before['snapshot'])['text'];b=json.loads(after['snapshot'])['text']
            return {'ok':True,'before_version':before['id'],'after_version':after['id'],'diff':'\n'.join(difflib.unified_diff(a.splitlines(),b.splitlines(),fromfile=before['id'],tofile=after['id'],lineterm=''))}
        if action=='find':
            vid=self.version(d)['id']
            return {**await self.engine(self.file(d,vid),'find',quote=body.get('quote')), 'version_id':vid}
        if body.get('agent') and not body.get('request_id'):
            # Same scoped input/base version has the same identity on uncertain retries.
            body={**body,'request_id':'agent-'+digest(t['id']+json.dumps(body,sort_keys=True,ensure_ascii=False))[:40]}
        rid=body.get('request_id')
        if not isinstance(rid,str) or not 8<=len(rid)<=100: raise ValueError('缺少操作标识')
        if action == 'export':
            # Export an immutable saved version. No browser handoff or current-version CAS.
            async with self.locks.setdefault(did, asyncio.Lock()):
                old=self.store.one('SELECT * FROM redline_operations WHERE document_id=? AND request_id=?',(did,rid))
                if old:
                    if old['request_hash']!=digest(json.dumps(body,sort_keys=True,ensure_ascii=False)):raise HTTPException(409,'操作标识已用于其他内容')
                    return json.loads(old['receipt'])
                vid=body.get('base_version')
                if not isinstance(vid,str) or not vid:raise ValueError('导出必须指定已保存的版本')
                source=self.file(d,vid);snapshot=json.loads(self.version(d,vid)['snapshot'])
                content=source.read_bytes()
                if body.get('clean'):
                    with tempfile.TemporaryDirectory(prefix='redline-export-') as tmp:
                        out=Path(tmp)/'clean.docx'
                        snapshot=await self.engine(source,'export',output=str(out),clean=True)
                        content=out.read_bytes();check_preserved_structures(source.read_bytes(),content)
                return self.publish(d,u,t,body,content,snapshot,vid)
        if action == 'save':
            return await self.write(u,t,d,body,data=data)
        # Serialize handoffs, while letting the browser flush through write().
        async with self.handoff_locks.setdefault(did, asyncio.Lock()):
            self.store.execute('UPDATE redline_documents SET yield_requested=1 WHERE document_id=?',(did,))
            try:
                deadline=time.monotonic()+40
                while True:
                    lease=self.store.one('SELECT * FROM redline_documents WHERE document_id=?',(did,))
                    if not lease['lease_id'] or lease['lease_until']<=time.time(): break
                    if time.monotonic()>deadline:
                        raise HTTPException(409,'编辑器尚未完成同步，请保存后重试')
                    await asyncio.sleep(.2)
                return await self.write(u,t,d,body,data=data)
            finally:
                self.store.execute('UPDATE redline_documents SET yield_requested=0 WHERE document_id=?',(did,))

    async def write(self,u,t,d,body,*,data=None):
        did=d['id'];action=body['action'];rid=body['request_id']
        async with self.locks.setdefault(did, asyncio.Lock()):
            old=self.store.one('SELECT * FROM redline_operations WHERE document_id=? AND request_id=?',(did,rid))
            if old:
                if old['request_hash']!=digest(json.dumps(body,sort_keys=True,ensure_ascii=False)): raise HTTPException(409,'操作标识已用于其他内容')
                return json.loads(old['receipt'])
            parent=self.version(d)['id']
            if body.get('base_version')!=parent: raise HTTPException(409,'合同已变化，请读取最新条款后重新生成修改')
            if action=='save':
                lease=self.store.one('SELECT * FROM redline_documents WHERE document_id=?',(did,))
                if lease['lease_id']!=body.get('client_id') or lease['lease_thread']!=t['id'] or lease['lease_until']<=time.time(): raise HTTPException(409,'编辑会话已过期；请保留本地内容并重新连接')
                if data is None: raise ValueError('缺少 DOCX 文件')
                if hashlib.sha256(data).hexdigest()!=body.get('content_hash'): raise ValueError('上传文件校验失败')
                validate_docx(data)
                if not body.get('review_events') and same_docx_content(self.file(d,parent).read_bytes(),data):
                    receipt={'saved':True,'unchanged':True,'document_id':did,'version_id':parent,'operation_id':rid}
                    self.store.execute('INSERT INTO redline_operations VALUES(?,?,?,?,?,?)',(did,rid,digest(json.dumps(body,sort_keys=True,ensure_ascii=False)),json.dumps(receipt),t['id'],time.time()))
                    return receipt
            elif action=='discussion':
                record=self.store.one('SELECT * FROM redline_discussions WHERE document_id=? AND comment_id=?',(did,body.get('id')))
                if not record:raise HTTPException(404,'历史批注不存在')
                c=json.loads(record['payload']);c['status']='resolved' if body.get('resolved') else 'open'
                data=self.file(d).read_bytes()
            elif action=='restore': data=self.file(d,body.get('restore_version')).read_bytes()
            with tempfile.TemporaryDirectory(prefix='redline-',dir=self.directory(d)) as tmp:
                out=Path(tmp)/'working.docx'
                if data is not None:
                    validate_docx(data);out.write_bytes(data)
                else:
                    if action not in {'apply','decide','comment','export'}: raise ValueError('无效文档操作')
                    args={k:v for k,v in body.items() if k in {'changes','decision','ids','operation','text','quote','context','block_id','id','clean'}}
                    snapshot=await self.engine(self.file(d),action,output=str(out),author={'name':'Contract Agent' if body.get('agent') else u['username'],'email':('agent+'+rid if body.get('agent') else u['id'])+'@workbench.local'},**args)
                    data=out.read_bytes()
                if action in {'apply','export','comment'}:check_preserved_structures(self.file(d,parent).read_bytes(),data)
                if action=='export': return self.publish(d,u,t,body,data,snapshot,parent)
                # Reopen exported bytes: IDs can change when Word serializes revisions.
                snapshot=await self.engine(out)
                _,summary,_=version_activity(body,json.loads(self.version(d,parent)['snapshot']),snapshot)
                return self.commit(d,u,data,snapshot,str(summary)[:200],parent,(body,t),discussion=c if action=='discussion' else None)

    def publish(self,d,u,t,body,data,snapshot,parent):
        validate_docx(data,clean=bool(body.get('clean')))
        aid=secrets.token_hex(12); dest=self.store.user_root(u['id'])/'published'/aid;dest.mkdir(parents=True)
        title=Path(d['filename']).stem+(' · 清洁版' if body.get('clean') else ' · 修订版')
        h=hashlib.sha256(data).hexdigest()
        report={'kind':'document','format':'docx','title':title,'content':'已保存原生 DOCX。'+('所有修订已处理，批注已从此副本移除。' if body.get('clean') else f'保留 {len(snapshot["changes"])} 项待审修订。'),'source_hash':d['source_hash'],'document_id':d['id'],'document_version':parent,'file_hash':h,'redline':True}
        receipt={'saved':True,'hash':h,'document_id':d['id'],'artifact_id':aid,'version_id':parent,'title':title,'download_url':f'/api/artifacts/{aid}/file?format=docx'}
        try:
            for filename,content in [('content.docx',data),('report.json',json.dumps(report,ensure_ascii=False).encode())]:
                with (dest/filename).open('wb') as f:f.write(content);f.flush();os.fsync(f.fileno())
            directory_fd=os.open(dest,os.O_RDONLY)
            try:os.fsync(directory_fd)
            finally:os.close(directory_fd)
            with self.store.connect() as db:
                db.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)',(aid,d['workspace_id'],t['id'],'document',title,digest(h+body['request_id']),d['source_hash'],time.time()))
                db.execute('INSERT INTO redline_operations VALUES(?,?,?,?,?,?)',(d['id'],body['request_id'],digest(json.dumps(body,sort_keys=True,ensure_ascii=False)),json.dumps(receipt),t['id'],time.time()))
        except BaseException: shutil.rmtree(dest);raise
        return receipt


def register_redline(app, service, user, thread):
    async def scope(request,did,writable=True):
        u=user(request);t=thread(u,request.query_params.get('thread_id'),writable)
        d=service.authorize(u,t,did)
        if not writable and t.get('archived_at') and not service.store.one('SELECT 1 FROM redline_documents WHERE document_id=?',(did,)):
            raise HTTPException(409,'请先恢复此对话，再创建工作副本')
        await service.ensure(d,u)
        return u,t,d

    @app.get('/api/redline/{did}')
    async def state(did:str,request:Request):
        _,_,d=await scope(request,did,False);return service.state(d)

    @app.get('/api/redline/{did}/file')
    async def file(did:str,request:Request,version_id:str=None):
        _,_,d=await scope(request,did,False);return FileResponse(service.file(d,version_id),media_type=MIME,filename=d['filename'])

    @app.patch('/api/redline/{did}/versions/{vid}/label')
    async def label(did:str,vid:str,request:Request):
        _,_,d=await scope(request,did)
        return service.label_version(d,vid,await request.json())

    @app.post('/api/redline/{did}/lease')
    async def lease(did:str,request:Request):
        _,t,d=await scope(request,did);return service.lease(d,t,await request.json())

    @app.post('/api/redline/{did}/operations')
    async def operation(did:str,request:Request):
        u,t,_=await scope(request,did);body=await request.json()
        if len(json.dumps(body))>1_000_000: raise HTTPException(413,'操作内容过大')
        return await service.apply(u,t,{**body,'document_id':did,'agent':False})

    @app.put('/api/redline/{did}/file')
    async def save(did:str,request:Request):
        u,t,_=await scope(request,did);data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>20_000_000:raise HTTPException(413,'DOCX 超过 20 MB')
        events=json.loads(request.headers.get('x-review-events','[]'))
        if not isinstance(events,list) or len(json.dumps(events))>8000:raise ValueError('修订操作记录过大')
        body={'review_events':events,'document_id':did,'action':'save','client_id':request.headers.get('x-editor-id'),'base_version':request.headers.get('x-document-version'),'request_id':request.headers.get('x-operation-id'),'content_hash':hashlib.sha256(data).hexdigest()}
        return await service.apply(u,t,body,data=bytes(data))
