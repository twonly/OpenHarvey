"""Owner-only, read-only analytics over retained product records.

No runtime calls, sandbox wakeups, inferred registrations, or analytics copies.
Content inspection is separate from the ordinary user-owned resource APIs.
"""
import csv
import io
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from .artifact_formats import files_for, PREVIEW_CSP, FORMATS
from .traces import redact
from .html_preview import render_preview

TZ = timezone(timedelta(hours=8))
PAGES = {'overview', 'users', 'runs', 'contracts', 'artifacts', 'models', 'runtime'}
SOURCES = ['SQLite 持久化记录', '已保存执行摘要', '已有原文、产出与历史快照']
NOTES = ['仅统计当前保留记录；清理与永久删除会影响历史。',
         '可能包含测试记录；没有统一测试标记。',
         '未采集访问、注册历史、下载、付费与标准留存；费用缺失不等于零。']


def is_ops_owner(u):
    owner = os.environ.get('CW_OPS_OWNER_USER_ID', '').strip()
    return bool(owner and u and u['id'] == owner)


def parsed(value, default=None):
    try:
        return json.loads(value) if value else ({} if default is None else default)
    except (ValueError, TypeError):
        return {} if default is None else default


def percentile(values, p):
    values = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0)
    if not values:
        return None
    position = (len(values)-1)*p
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi]-values[lo])*(position-lo)


class Filters:
    def __init__(self, query, owner):
        today = datetime.now(TZ).date()
        try:
            start = datetime.strptime(query.get('start', str(today-timedelta(days=6))), '%Y-%m-%d').replace(tzinfo=TZ)
            end = datetime.strptime(query.get('end', str(today)), '%Y-%m-%d').replace(tzinfo=TZ)+timedelta(days=1)
            self.limit = min(100, max(1, int(query.get('limit', '50'))))
            self.offset = max(0, int(query.get('offset', '0')))
            self.queue_offset = max(0, int(query.get('queue_offset', '0')))
            self.binding_offset = max(0, int(query.get('binding_offset', '0')))
            self.paused_offset = max(0, int(query.get('paused_offset', '0')))
        except (ValueError, TypeError):
            raise HTTPException(422, '日期或分页参数无效') from None
        if end <= start or (end-start).days > 366:
            raise HTTPException(422, '请选择不超过 366 天的有效日期范围')
        self.start, self.end = start.timestamp(), end.timestamp()
        self.start_date, self.end_date = start.date().isoformat(), (end-timedelta(days=1)).date().isoformat()
        self.owner = owner
        self.kind = query.get('account_kind', '')
        if self.kind not in {'', 'demo', 'personal'}:
            raise HTTPException(422, '账号类型无效')
        self.uid = query.get('user_id', '')
        self.exclude = query.get('exclude_owner', '1') != '0'
        self.status = query.get('status', '')
        if self.status not in {'', 'completed', 'failed', 'interrupted', 'running'}:
            raise HTTPException(422, '执行状态无效')
        self.model = query.get('model', '')[:200]
        self.search = query.get('q', '')[:120]
        self.active_only = query.get('active_only') == '1'
        self.sort = query.get('sort', 'created')
        self.order = 'ASC' if query.get('order') == 'asc' else 'DESC'

    def users(self):
        where, args = ['1=1'], []
        if self.exclude:
            where.append('u.id != ?'); args.append(self.owner)
        if self.uid:
            where.append('u.id = ?'); args.append(self.uid)
        if self.kind:
            where.append('u.account_kind = ?'); args.append(self.kind)
        return ' AND '.join(where), args

    def dated(self, column):
        return f'{column} >= ? AND {column} < ?', [self.start, self.end]


class Operations:
    def __init__(self, app):
        self.app, self.store = app, app.state.store
        self.cache = {}

    @contextmanager
    def read(self):
        db = sqlite3.connect(self.store.path.as_uri()+'?mode=ro', uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def rows(db, sql, args=()):
        return [dict(r) for r in db.execute(sql, args)]

    @staticmethod
    def scalar(db, sql, args=()):
        return db.execute(sql, args).fetchone()[0]

    def run_query(self, f):
        uw, args = f.users()
        dw, dateargs = f.dated('r.created')
        where = uw+' AND '+dw
        args += dateargs
        if f.status:
            where += " AND json_extract(r.summary,'$.status')=?"; args.append(f.status)
        if f.model == '__missing__':
            where += " AND json_extract(r.summary,'$.model') IS NULL"
        elif f.model:
            where += " AND json_extract(r.summary,'$.model')=?"; args.append(f.model)
        if f.search:
            where += ' AND (u.username LIKE ? OR t.title LIKE ? OR w.title LIKE ?)'
            args += ['%'+f.search+'%']*3
        return (' FROM trace_runs r JOIN users u ON u.id=r.user_id'
                ' LEFT JOIN threads t ON t.id=r.thread_id LEFT JOIN workspaces w ON w.id=t.workspace_id WHERE '+where), args

    def metadata(self, db, f):
        uw, args = f.users()
        coverage = dict(db.execute('SELECT MIN(r.created) first_record, MAX(r.created) last_record, COUNT(*) retained_runs'
                                  ' FROM trace_runs r JOIN users u ON u.id=r.user_id WHERE '+uw, args).fetchone())
        synced = self.scalar(db, 'SELECT MAX(h.synced) FROM e2b_history h JOIN threads t ON t.id=h.thread_id JOIN workspaces w ON w.id=t.workspace_id JOIN users u ON u.id=w.user_id WHERE '+uw, args)
        return {'as_of': time.time(), 'sources': SOURCES, 'notes': NOTES, 'coverage': coverage,
                'snapshot_synced': synced, 'timezone': 'Asia/Shanghai',
                'period': {'start': f.start_date, 'end': f.end_date}, 'comparison': None}

    def run_metrics(self, db, f):
        query, args = self.run_query(f)
        j=lambda k: "json_extract(r.summary,'$."+k+"')"
        valid=lambda k: "json_type(r.summary,'$."+k+"') IN ('integer','real') AND "+j(k)+">=0"
        states={s:self.scalar(db,'SELECT COUNT(*)'+query+' AND '+j('status')+'=?',args+[s]) for s in ('completed','failed','interrupted','running')}
        count=self.scalar(db,'SELECT COUNT(*)'+query,args)
        ended = sum(states[s] for s in ('completed','failed','interrupted'))
        dq=query+' AND '+j('status')+" IN ('completed','failed','interrupted') AND "+valid('duration')
        duration_count=self.scalar(db,'SELECT COUNT(*)'+dq,args)
        def pct(p):
            if not duration_count:return None
            position=(duration_count-1)*p;offset=math.floor(position)
            values=[r[0] for r in db.execute('SELECT '+j('duration')+dq+' ORDER BY '+j('duration')+' LIMIT 2 OFFSET ?',args+[offset])]
            return values[0]+((values[-1]-values[0])*(position-offset))
        aggregates={}
        for name in ('tokens','cost'):
            row=db.execute('SELECT SUM('+j(name)+'),COUNT(*)'+query+' AND '+valid(name),args).fetchone()
            aggregates[name]=row
        return {'runs':count, 'states':states, 'ended':ended, 'failure_rate':states['failed']/ended if ended else None,
                'interruption_rate':states['interrupted']/ended if ended else None,
                'duration_p50':pct(.5), 'duration_p95':pct(.95), 'duration_samples':duration_count,
                'tokens':aggregates['tokens'][0], 'token_samples':aggregates['tokens'][1],
                'cost':aggregates['cost'][0], 'cost_samples':aggregates['cost'][1],
                'tool_errors':self.scalar(db,'SELECT COALESCE(SUM('+j('tool_errors')+'),0)'+query,args)}

    def overview(self, db, f):
        uw, ua = f.users()
        metrics = self.run_metrics(db,f)
        active = self.scalar(db, '''SELECT COUNT(DISTINCT id) FROM (
            SELECT u.id FROM queued_messages q JOIN users u ON u.id=q.user_id WHERE '''+uw+''' AND q.created>=? AND q.created<?
            UNION SELECT u.id FROM trace_runs r JOIN users u ON u.id=r.user_id WHERE '''+uw+' AND r.created>=? AND r.created<?)', ua+[f.start,f.end]+ua+[f.start,f.end])
        stock = {}
        for name, query in {
            'users':'SELECT COUNT(*) FROM users u WHERE ',
            'workspaces':'SELECT COUNT(*) FROM workspaces w JOIN users u ON u.id=w.user_id WHERE ',
            'documents':'SELECT COUNT(*) FROM documents d JOIN users u ON u.id=d.user_id WHERE ',
            'artifacts':'SELECT COUNT(*) FROM artifacts a JOIN workspaces w ON w.id=a.workspace_id JOIN users u ON u.id=w.user_id WHERE ',
        }.items():
            stock[name] = self.scalar(db,query+uw,ua)
        def count_period(table, alias, joins):
            return self.scalar(db,f'SELECT COUNT(*) FROM {table} {alias} '+joins+' WHERE '+uw+f' AND {alias}.created>=? AND {alias}.created<?',ua+[f.start,f.end])
        metrics.update(active_users=active, new_workspaces=count_period('workspaces','w','JOIN users u ON u.id=w.user_id'),
                       artifacts=count_period('artifacts','a','JOIN workspaces w ON w.id=a.workspace_id JOIN users u ON u.id=w.user_id'),
                       queued_requests=count_period('queued_messages','q','JOIN users u ON u.id=q.user_id'))
        trend = {}
        for day in range(int((f.end-f.start)/86400)):
            label=datetime.fromtimestamp(f.start+day*86400,TZ).date().isoformat()
            trend[label]={'day':label,'runs':0,'completed':0,'artifacts':0,'active_users':0}
        rq, ra = self.run_query(f)
        for r in self.rows(db,"SELECT date(r.created,'unixepoch','+8 hours') day, COUNT(*) runs, SUM(json_extract(r.summary,'$.status')='completed') completed"+rq+' GROUP BY day',ra):
            trend[r['day']].update(r)
        for r in self.rows(db,"SELECT date(a.created,'unixepoch','+8 hours') day, COUNT(*) artifacts FROM artifacts a JOIN workspaces w ON w.id=a.workspace_id JOIN users u ON u.id=w.user_id WHERE "+uw+' AND a.created>=? AND a.created<? GROUP BY day',ua+[f.start,f.end]):
            trend[r['day']].update(r)
        for r in self.rows(db,"SELECT day, COUNT(DISTINCT id) active_users FROM (SELECT u.id,date(q.created,'unixepoch','+8 hours') day FROM queued_messages q JOIN users u ON u.id=q.user_id WHERE "+uw+" AND q.created>=? AND q.created<? UNION SELECT u.id,date(r.created,'unixepoch','+8 hours') day FROM trace_runs r JOIN users u ON u.id=r.user_id WHERE "+uw+' AND r.created>=? AND r.created<?) GROUP BY day',ua+[f.start,f.end]+ua+[f.start,f.end]):
            trend[r['day']].update(r)
        return {'metrics':metrics,'stock':stock,'trend':list(trend.values()),
                'recent':self.runs(db,f,limit=6)['items'],
                'issues':self.run_rows(db,rq+" AND json_extract(r.summary,'$.status') IN ('failed','interrupted')",ra,6,0),
                'runtime':self.runtime(db,f,compact=True)}

    def run_rows(self, db, query, args, limit, offset, sort='r.created DESC'):
        rows=self.rows(db, 'SELECT r.id,r.thread_id,r.user_id,r.message_id,r.created,u.username,u.account_kind,w.id workspace_id,w.title workspace_title,t.title thread_title,r.summary'+query+' ORDER BY '+sort+' LIMIT ? OFFSET ?',args+[limit,offset])
        for row in rows:
            summary=parsed(row.pop('summary'))
            row.update({k:summary.get(k) for k in ('status','model','duration','tokens','cost','tool_errors','tool_count')})
            row['thread_artifacts']=self.scalar(db,'SELECT COUNT(*) FROM artifacts WHERE thread_id=?',(row['thread_id'],))
            q=db.execute('SELECT body FROM queued_messages WHERE thread_id=? AND message_id=?',(row['thread_id'],row['message_id'])).fetchone()
            row['explicit_skill']=parsed(q['body']).get('skill') if q else None
        return rows

    def runs(self, db, f, limit=None):
        query,args=self.run_query(f)
        sort={'created':'r.created','duration':"json_extract(r.summary,'$.duration')",'tokens':"json_extract(r.summary,'$.tokens')",'username':'u.username'}.get(f.sort,'r.created')+' '+f.order+',r.id'
        return {'items':self.run_rows(db,query,args,limit or f.limit,f.offset,sort),
                'total':self.scalar(db,'SELECT COUNT(*)'+query,args),'metrics':self.run_metrics(db,f)}

    def users(self, db, f):
        uw,args=f.users()
        if f.search:
            uw+=' AND (u.username LIKE ? OR u.email LIKE ?)';args+=['%'+f.search+'%']*2
        if f.active_only:
            uw+=' AND (EXISTS(SELECT 1 FROM trace_runs r WHERE r.user_id=u.id AND r.created>=? AND r.created<?) OR EXISTS(SELECT 1 FROM queued_messages q WHERE q.user_id=u.id AND q.created>=? AND q.created<?))'
            args += [f.start,f.end]*2
        select='''SELECT u.id,u.username,u.email,u.role,u.account_kind,u.active,u.expires_at,u.cleaned_at,u.trial_total,u.trial_used,
            (SELECT MAX(created) FROM trace_runs WHERE user_id=u.id) last_execution,
            (SELECT MAX(created) FROM queued_messages WHERE user_id=u.id) last_request,
            (SELECT COUNT(*) FROM workspaces WHERE user_id=u.id) workspaces,
            (SELECT COUNT(*) FROM providers WHERE org_id='user:'||u.id AND enabled=1) configured_providers
            FROM users u WHERE '''
        sort={'username':'u.username','created':'MAX(COALESCE(last_request,0),COALESCE(last_execution,0))'}.get(f.sort,'u.username')+' '+f.order+',u.id'
        rows=self.rows(db,select+uw+' ORDER BY '+sort+' LIMIT ? OFFSET ?',args+[f.limit,f.offset])
        for r in rows:
            r['last_observed']=max(r.pop('last_execution') or 0,r.pop('last_request') or 0) or None
            r['effective_active']=bool(r['active'] and (not r['expires_at'] or r['expires_at']>time.time()))
            r['runs']=self.scalar(db,'SELECT COUNT(*) FROM trace_runs WHERE user_id=? AND created>=? AND created<?',(r['id'],f.start,f.end))
            r['artifacts']=self.scalar(db,'SELECT COUNT(*) FROM artifacts a JOIN workspaces w ON w.id=a.workspace_id WHERE w.user_id=? AND a.created>=? AND a.created<?',(r['id'],f.start,f.end))
        return {'items':rows,'total':self.scalar(db,'SELECT COUNT(*) FROM users u WHERE '+uw,args)}

    def contracts(self, db, f):
        uw,args=f.users();where=uw+' AND w.created>=? AND w.created<?';args += [f.start,f.end]
        if f.search:
            where+=' AND w.title LIKE ?';args.append('%'+f.search+'%')
        base=' FROM workspaces w JOIN users u ON u.id=w.user_id WHERE '+where
        sort={'created':'w.created','username':'u.username','title':'w.title'}.get(f.sort,'w.created')+' '+f.order+',w.id'
        rows=self.rows(db,'''SELECT w.id,w.title,w.created,w.last_activity_at,w.deleted_at,w.backend,u.id user_id,u.username,
            (SELECT COUNT(*) FROM threads WHERE workspace_id=w.id) threads,
            (SELECT COUNT(*) FROM documents WHERE workspace_id=w.id) documents,
            (SELECT COUNT(*) FROM artifacts WHERE workspace_id=w.id) artifacts'''+base+' ORDER BY '+sort+' LIMIT ? OFFSET ?',args+[f.limit,f.offset])
        return {'items':rows,'total':self.scalar(db,'SELECT COUNT(*)'+base,args),
                'feedback':self.rows(db,'''SELECT f.decision,COUNT(*) count FROM risk_feedback f JOIN artifacts a ON a.id=f.artifact_id
                    JOIN workspaces w ON w.id=a.workspace_id JOIN users u ON u.id=w.user_id WHERE '''+uw+'''
                    AND f.created>=? AND f.created<? AND NOT EXISTS(SELECT 1 FROM risk_feedback n WHERE n.artifact_id=f.artifact_id AND n.risk_id=f.risk_id AND n.revision>f.revision) GROUP BY f.decision''',f.users()[1]+[f.start,f.end])}

    def models(self, db, f):
        rq,ra=self.run_query(f)
        names=self.rows(db,"SELECT DISTINCT COALESCE(json_extract(r.summary,'$.model'),'未记录') model"+rq,ra)
        items=[]
        for name in names:
            sub=Filters({'start':f.start_date,'end':f.end_date,'exclude_owner':'1' if f.exclude else '0','account_kind':f.kind,'user_id':f.uid,'model':name['model'] if name['model']!='未记录' else '__missing__', 'status':f.status},f.owner)
            sub.search=f.search
            items.append({'model':name['model'],**self.run_metrics(db,sub)})
        sort=f.sort if f.sort in {'runs','tokens','duration_p50','failure_rate'} else 'runs'
        items.sort(key=lambda r:(r.get(sort) is None, (r.get(sort) or 0)*(1 if f.order=='ASC' else -1)))
        uw,ua=f.users()
        # Operation probes share the quota table but are not conversational requests.
        extra='';extra_args=[]
        if f.model or f.status:
            checks=['m.thread_id=q.thread_id','m.message_id=q.message_id']
            if f.model=='__missing__':checks.append("json_extract(m.summary,'$.model') IS NULL")
            elif f.model:checks.append("json_extract(m.summary,'$.model')=?");extra_args.append(f.model)
            if f.status:checks.append("json_extract(m.summary,'$.status')=?");extra_args.append(f.status)
            extra=' AND EXISTS(SELECT 1 FROM trace_runs m WHERE '+' AND '.join(checks)+')'
        quota=self.rows(db,'''SELECT tr.platform,tr.status,COUNT(*) count,SUM(tr.proxy_calls) proxy_calls
            FROM trial_runs tr JOIN users u ON u.id=tr.user_id JOIN queued_messages q ON q.id=tr.queue_id
            WHERE '''+uw+' AND q.created>=? AND q.created<?'+extra+' GROUP BY tr.platform,tr.status',ua+[f.start,f.end]+extra_args)
        return {'items':items[f.offset:f.offset+f.limit],'total':len(items),'metrics':self.run_metrics(db,f),'quota':quota,
                'next_quota_reset':(int(time.time()//86400)+1)*86400,'quota_timezone':'UTC'}

    def artifacts(self, db, f):
        uw,ua=f.users()
        base=' FROM artifacts a JOIN workspaces w ON w.id=a.workspace_id JOIN users u ON u.id=w.user_id WHERE '+uw+' AND a.created>=? AND a.created<?'
        args=ua+[f.start,f.end]
        if f.search:base+=' AND (a.title LIKE ? OR w.title LIKE ?)';args+=['%'+f.search+'%']*2
        sort={'created':'a.created','username':'u.username'}.get(f.sort,'a.created')+' '+f.order+',a.id'
        rows=self.rows(db,'SELECT a.id,a.title,a.kind,a.created,a.thread_id,w.id workspace_id,w.title workspace_title,u.id user_id,u.username'+base+' ORDER BY '+sort+' LIMIT ? OFFSET ?',args+[f.limit,f.offset])
        for row in rows:
            path=self.store.user_root(row['user_id'])/'published'/row['id']/'report.json'
            body=parsed(path.read_text()) if path.is_file() else {}
            row['format']=body.get('format','md') if body else None
            row['available']=bool(body)
        return {'items':rows,'total':self.scalar(db,'SELECT COUNT(*)'+base,args),'dataset':'artifacts'}

    def runtime(self, db, f, compact=False):
        uw,ua=f.users()
        queue=self.rows(db,'''SELECT q.id,q.thread_id,q.user_id,u.username,q.status,q.stage,q.created FROM queued_messages q
            JOIN users u ON u.id=q.user_id WHERE '''+uw+" AND q.status IN ('queued','dispatching','submitted','failed') ORDER BY q.created,q.id LIMIT ? OFFSET ?",ua+([6,0] if compact else [f.limit,f.queue_offset]))
        paused=self.rows(db,'''SELECT s.thread_id,s.reason,u.username FROM queue_state s JOIN threads t ON t.id=s.thread_id
            JOIN workspaces w ON w.id=t.workspace_id JOIN users u ON u.id=w.user_id WHERE '''+uw+' AND s.paused=1 ORDER BY s.thread_id LIMIT ? OFFSET ?',ua+[f.limit,f.paused_offset])
        states=self.rows(db,'''SELECT b.status,COUNT(*) count FROM e2b_bindings b JOIN workspaces w ON w.id=b.workspace_id
            JOIN users u ON u.id=w.user_id WHERE '''+uw+' GROUP BY b.status',ua)
        result={'queue':queue,'paused':paused,'sandboxes':states,'next_quota_reset':(int(time.time()//86400)+1)*86400,
                'paused_total':self.scalar(db,'SELECT COUNT(*) FROM queue_state s JOIN threads t ON t.id=s.thread_id JOIN workspaces w ON w.id=t.workspace_id JOIN users u ON u.id=w.user_id WHERE '+uw+' AND s.paused=1',ua),
                'queue_total':self.scalar(db,"SELECT COUNT(*) FROM queued_messages q JOIN users u ON u.id=q.user_id WHERE "+uw+" AND q.status IN ('queued','dispatching','submitted','failed')",ua)}
        from .accounts import LIMITS
        platform=db.execute('SELECT value FROM platform_settings WHERE id=1').fetchone()
        limits=LIMITS | (parsed(platform['value']) if platform else {})
        result['platform_quota']={
            'daily_used':self.scalar(db,"SELECT COUNT(*) FROM trial_runs WHERE platform=1 AND day=? AND status!='refunded'",(datetime.now(timezone.utc).date().isoformat(),)),
            'daily_limit':limits['global_daily'],
            'running':self.scalar(db,"SELECT COUNT(*) FROM trial_runs WHERE status='running'"),
            'concurrency_limit':limits['global_concurrency'],
            'scope':'全平台实时额度，不受看板筛选影响'}
        if not compact:
            result['bindings']=self.rows(db,'''SELECT w.id,w.title,u.username,b.status,b.generation,b.started,b.synced,b.last_activity
                FROM e2b_bindings b JOIN workspaces w ON w.id=b.workspace_id JOIN users u ON u.id=w.user_id
                WHERE '''+uw+' ORDER BY b.last_activity DESC,w.id LIMIT ? OFFSET ?',ua+[f.limit,f.binding_offset])
            result['bindings_total']=self.scalar(db,'SELECT COUNT(*) FROM e2b_bindings b JOIN workspaces w ON w.id=b.workspace_id JOIN users u ON u.id=w.user_id WHERE '+uw,ua)
            eventbase=' FROM e2b_events e JOIN workspaces w ON w.id=e.workspace_id JOIN users u ON u.id=w.user_id WHERE '+uw+' AND e.created>=? AND e.created<?'
            result['items']=self.rows(db,'SELECT e.id,e.workspace_id,e.thread_id,e.kind,e.created,u.username'+eventbase+' ORDER BY e.created '+f.order+',e.id LIMIT ? OFFSET ?',ua+[f.start,f.end,f.limit,f.offset])
            result['total']=self.scalar(db,'SELECT COUNT(*)'+eventbase,ua+[f.start,f.end])
        return result

    def listing(self, page, f):
        key=(page,json.dumps(vars(f),sort_keys=True))
        cached=self.cache.get(key)
        if page=='overview' and cached and time.monotonic()-cached[0]<10:
            return cached[1]
        with self.read() as db:
            result={**getattr(self,page)(db,f),'meta':self.metadata(db,f),'offset':f.offset,'limit':f.limit}
        if page=='overview':
            if len(self.cache)>=32:self.cache.clear()
            self.cache[key]=(time.monotonic(),result)
        return result

    def safe_content(self, uid, value):
        u=self.store.one('SELECT id,org_id,account_kind,role FROM users WHERE id=?',(uid,))
        if not u:raise HTTPException(410,'账号内容已清理')
        secrets=self.app.state.traces.credentials(self.app.state.models.scope(u))
        for p in (self.store.user_root(uid)/'threads').glob('*/.publish-token'):
            if p.is_file():secrets.append(p.read_text())
        # Stored E2B output was already scrubbed on ingestion; never query a live VM.
        return redact(value,secrets)

    def audit(self, viewer, uid, target):
        if viewer['id']!=uid:self.app.state.settings.audit(viewer,'ops.content.read',target)

    def contract_detail(self, viewer, wid):
        w=self.store.one('SELECT id,user_id,title,created,deleted_at,backend FROM workspaces WHERE id=?',(wid,))
        if not w:raise HTTPException(410,'合同不存在或已清理')
        self.audit(viewer,w['user_id'],'workspace:'+wid)
        docs=self.store.all('SELECT id,filename,suffix,source_hash,thread_id FROM documents WHERE workspace_id=?',(wid,))
        arts=self.store.all('SELECT id,title,kind,thread_id,created,source_hash FROM artifacts WHERE workspace_id=? ORDER BY created DESC',(wid,))
        for a in arts:
            path=self.store.user_root(w['user_id'])/'published'/a['id']/'report.json'
            body=parsed(path.read_text()) if path.is_file() else {}
            a.update(format=body.get('format','md') if body else None,available=bool(body),findings=body.get('findings',[]) if a['kind']=='review' else [])
            a['feedback']=self.store.all('SELECT risk_id,decision,note,revision,created FROM risk_feedback WHERE artifact_id=? ORDER BY revision',(a['id'],))
        return self.safe_content(w['user_id'],{'workspace':w,'documents':docs,'artifacts':arts,
            'threads':self.store.all('SELECT id,title,created,archived_at,deleted_at FROM threads WHERE workspace_id=? ORDER BY created',(wid,)),
            'sandbox':self.store.one('SELECT status,generation,started,synced,last_activity,error FROM e2b_bindings WHERE workspace_id=?',(wid,))})

    def run_detail(self, viewer, rid):
        r=self.store.one('SELECT * FROM trace_runs WHERE id=?',(rid,))
        if not r:raise HTTPException(410,'执行记录不存在或已清理')
        self.audit(viewer,r['user_id'],'run:'+rid)
        history=self.store.one('SELECT messages,synced FROM e2b_history WHERE thread_id=?',(r['thread_id'],))
        messages=parsed(history['messages'],[]) if history else []
        start=next((i for i,m in enumerate(messages) if m.get('info',{}).get('id')==r['message_id']),None)
        group=[]
        if start is not None:
            for m in messages[start:]:
                info=m.get('info',{})
                if group and info.get('role')=='user' and any(p.get('type') in {'text','file'} and not p.get('synthetic') for p in m.get('parts',[])):break
                parts=[]
                for p in m.get('parts',[]):
                    if p.get('synthetic'):continue
                    if p.get('type')=='text':parts.append({'type':'text','text':p.get('text','')})
                    elif p.get('type')=='file':parts.append({'type':'file','filename':p.get('filename','附件')})
                    elif p.get('type')=='tool':parts.append({'type':'tool','tool':p.get('tool'),'state':{k:p.get('state',{}).get(k) for k in ('status','input','output','error','time','title')}})
                group.append({'info':{k:info[k] for k in ('id','role','time','modelID','providerID','tokens','cost','error','finish') if k in info},'parts':parts})
        cfg=self.store.one('SELECT config FROM execution_configs WHERE id=?',(r['execution_id'],))
        t=self.store.one('SELECT workspace_id FROM threads WHERE id=?',(r['thread_id'],))
        r['summary']=parsed(r['summary'])
        return self.safe_content(r['user_id'],{'run':r,'messages':group,'configuration':parsed(cfg['config']) if cfg else None,
            'synced':history['synced'] if history else None,'content_status':'已保存快照' if group else '持久化快照不可用；未请求运行时',
            'workspace_id':t['workspace_id'] if t else None,
            'artifacts':self.store.all('SELECT id,title,kind,created FROM artifacts WHERE thread_id=? ORDER BY created',(r['thread_id'],)),
            'artifact_association':'对话级产出；未推定属于本轮'})

    def document(self, viewer, did, raw=False):
        d=self.store.one('SELECT * FROM documents WHERE id=?',(did,))
        if not d:raise HTTPException(410,'原文不存在或已清理')
        self.audit(viewer,d['user_id'],'document:'+did)
        root=self.store.user_root(d['user_id'])/'sources'/did
        path=root/('source'+d['suffix'] if raw else 'document.json')
        self.check_path(path,root)
        if raw:return FileResponse(path,filename=d['filename'],content_disposition_type='attachment')
        return self.safe_content(d['user_id'],{'document':d,'mapping':parsed(path.read_text())})

    @staticmethod
    def check_path(path, root):
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            raise HTTPException(410,'文件缺失或已清理')

    def artifact(self, viewer, aid, action='', fmt=''):
        a=self.store.one('SELECT a.*,w.user_id FROM artifacts a JOIN workspaces w ON w.id=a.workspace_id WHERE a.id=?',(aid,))
        if not a:raise HTTPException(410,'产出不存在或已清理')
        self.audit(viewer,a['user_id'],'artifact:'+aid)
        root=self.store.user_root(a['user_id'])/'published'/aid
        path=root/'report.json';self.check_path(path,root)
        body=parsed(path.read_text());files=files_for(body)
        if 'md' in files and not (root/files['md']).is_file():files['md']='report.md'
        if not action:
            return self.safe_content(a['user_id'],{'artifact':a,'report':body,'formats':list(files)})
        fmt=fmt or body.get('format','md')
        if fmt not in files:raise HTTPException(422,'此格式未保存')
        path=root/files[fmt];self.check_path(path,root)
        if action=='preview':
            if fmt not in {'html','svg'}:raise HTTPException(422,'该格式使用文本预览')
            content=self.safe_content(a['user_id'],path.read_text())
            if fmt=='html':
                documents=self.store.all('SELECT id,filename,source_hash FROM documents WHERE workspace_id=? AND (thread_id IS NULL OR thread_id=?)',(a['workspace_id'],a['thread_id']))
                primary=self.store.one('SELECT d.source_hash FROM documents d JOIN workspaces w ON w.document_id=d.id WHERE w.id=?',(a['workspace_id'],))
                if not primary or primary['source_hash']!=a['source_hash']:documents=[]
                for document in documents:
                    mapping=self.store.user_root(a['user_id'])/'sources'/document['id']/'document.json'
                    mapped=parsed(mapping.read_text()) if mapping.is_file() else {}
                    if mapped.get('source_hash')==document['source_hash']:
                        document['locations']={s['id']:{'page':s.get('page'),'ordinal':i+1,'preview':s.get('text','')[:180]} for i,s in enumerate(mapped.get('segments',[]))}
                content=render_preview(content,documents,aid)
                content=self.safe_content(a['user_id'],content)
            return Response(content,media_type=FORMATS[fmt],headers={'Content-Security-Policy':PREVIEW_CSP})
        # Keep original downloadable bytes; the endpoint is authenticated and audited.
        return FileResponse(path,filename=a['title'].replace('/','_')+'.'+fmt,content_disposition_type='attachment')


def register_ops(app, user, root):
    ops=Operations(app);app.state.ops=ops

    def owner(request):
        u=user(request)
        if not is_ops_owner(u):raise HTTPException(403,'仅看板所有者可访问')
        return u

    @app.get('/ops')
    @app.get('/ops/detail')
    def page(request:Request):
        owner(request)
        return FileResponse(root/'static/ops.html',headers={'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"})

    @app.get('/api/ops/options')
    def options(request:Request):
        owner(request)
        return {'users':ops.store.all('SELECT id,username,account_kind FROM users ORDER BY username'),
                'models':ops.store.all("SELECT DISTINCT json_extract(summary,'$.model') model FROM trace_runs WHERE json_extract(summary,'$.model') IS NOT NULL ORDER BY model")}

    @app.get('/api/ops/export/{section}')
    def export(section:str,request:Request):
        u=owner(request)
        if section not in PAGES-{'overview'}:raise HTTPException(404,'导出类型不存在')
        f=Filters(request.query_params,u['id']);f.offset=0;f.limit=100
        # One consistent SQLite read transaction for every exported page.
        output=io.StringIO();writer=None
        with ops.read() as db:
            while True:
                data=getattr(ops,section)(db,f);rows=data.get('items',[])
                for row in rows:
                    flat={k:v for k,v in row.items() if not isinstance(v,(dict,list))}
                    if writer is None:writer=csv.DictWriter(output,fieldnames=list(flat),extrasaction='ignore');writer.writeheader()
                    writer.writerow({k:("'"+str(v) if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r')) else v) for k,v in flat.items()})
                f.offset+=len(rows)
                if not rows or f.offset>=data['total']:break
        app.state.settings.audit(u,'ops.export',section)
        return Response('\ufeff'+output.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="openharvey-{section}.csv"'})

    @app.get('/api/ops/users/{uid}')
    def user_detail(uid:str,request:Request):
        u=owner(request);q=dict(request.query_params);q.update(user_id=uid,exclude_owner='0',account_kind='',q='',offset='0',active_only='',model='',status='')
        f=Filters(q,u['id']);data=ops.listing('users',f)
        if not data['items']:raise HTTPException(410,'账号不存在或已清理')
        return {'user':data['items'][0],'runs':ops.listing('runs',f),'contracts':ops.listing('contracts',f),'meta':data['meta']}

    @app.get('/api/ops/runs/{rid}')
    def run_detail(rid:str,request:Request):return ops.run_detail(owner(request),rid)

    @app.get('/api/ops/contracts/{wid}')
    def contract_detail(wid:str,request:Request):return ops.contract_detail(owner(request),wid)

    @app.get('/api/ops/documents/{did}')
    def document(did:str,request:Request):return ops.document(owner(request),did)

    @app.get('/api/ops/documents/{did}/file')
    def document_file(did:str,request:Request):return ops.document(owner(request),did,True)

    @app.get('/api/ops/artifacts/{aid}')
    def artifact(aid:str,request:Request):return ops.artifact(owner(request),aid)

    @app.get('/api/ops/artifacts/{aid}/{action}')
    def artifact_file(aid:str,action:str,request:Request,format:str=''):
        u=owner(request)
        if action not in {'file','preview'}:raise HTTPException(404,'接口不存在')
        return ops.artifact(u,aid,action,format)

    @app.get('/api/ops/{section}')
    def listing(section:str,request:Request):
        u=owner(request)
        if section not in PAGES:raise HTTPException(404,'看板不存在')
        return ops.listing(section,Filters(request.query_params,u['id']))
