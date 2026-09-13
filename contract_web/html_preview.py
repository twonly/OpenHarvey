"""Decorate visible HTML citations only; saved/downloaded bytes stay untouched."""
import html
import json
import re
from html.parser import HTMLParser

REFERENCE=re.compile(r'【(?:D([a-f0-9]{12}):)?B(\d+)(?:-B(\d+))?】')
RAW={'script','style','textarea','title','noscript'}

def render_preview(content,documents,artifact_id):
    docs={d['id']:d for d in documents}
    explicit=set(re.findall(r'【D([a-f0-9]{12}):B',content))
    references=[]
    def citation(match):
        did,start,end=match.groups()
        if len(start)>12 or len(end or start)>12:return '<span>来源待核对</span>'
        start=int(start);end=int(end) if end else start
        if not did and len(docs)==1 and explicit.issubset(docs):did=next(iter(docs))
        doc=docs.get(did);locations=(doc or {}).get('locations',{})
        if not doc or end<start or end-start>100000 or any('B'+str(i) not in locations for i in range(start,end+1)):
            return '<span title="引用缺少来源或原文位置无效">来源待核对</span>'
        first,last=locations['B'+str(start)],locations['B'+str(end)]
        if first.get('page') and last.get('page'):
            where=f'PDF 第{first["page"]}页' if first['page']==last['page'] else f'PDF 第{first["page"]}–{last["page"]}页'
        else:
            a,b=first.get('ordinal',start+1),last.get('ordinal',end+1)
            where=f'第{a}段' if a==b else f'第{a}–{b}段'
        index=len(references)
        references.append({'type':'workbench.citation','artifactId':artifact_id,'docid':did,'block':'B'+str(start),'end':'B'+str(end),'hash':doc['source_hash']})
        title=doc.get('filename','原文')+' · '+where+'\n'+first.get('preview','')
        return f'<button type="button" class="workbench-source-link" data-workbench-reference="{index}" title="{html.escape(title,quote=True)}">查看原文 · {html.escape(where)}</button>'

    class Decorator(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=False);self.output=[];self.raw=None
        def handle_starttag(self,tag,attrs):
            self.output.append(self.get_starttag_text())
            if tag in RAW:self.raw=tag
        def handle_startendtag(self,tag,attrs):self.output.append(self.get_starttag_text())
        def handle_endtag(self,tag):
            self.output.append(f'</{tag}>')
            if tag==self.raw:self.raw=None
        def handle_data(self,data):self.output.append(data if self.raw else REFERENCE.sub(citation,data))
        def handle_entityref(self,name):self.output.append('&'+name+';')
        def handle_charref(self,name):self.output.append('&#'+name+';')
        def handle_comment(self,data):self.output.append('<!--'+data+'-->')
        def handle_decl(self,decl):self.output.append('<!'+decl+'>')
        def handle_pi(self,data):self.output.append('<?'+data+'>')
    parser=Decorator();parser.feed(content);parser.close()
    if not references:return ''.join(parser.output)
    data=json.dumps(references,ensure_ascii=True).replace('<','\\u003c')
    bridge='''<style>.workbench-source-link{font:inherit;font-size:12px;color:#315b91;background:#edf4fc;border:1px solid #d8e4f2;border-radius:5px;padding:2px 6px;cursor:pointer;vertical-align:baseline}.workbench-source-link:focus-visible{outline:2px solid #315b91;outline-offset:2px}</style>
<script>(()=>{const refs=REFERENCES;document.addEventListener('click',e=>{const button=e.target.closest?.('[data-workbench-reference]');if(!button)return;const ref=refs[Number(button.dataset.workbenchReference)];if(!ref)return;e.preventDefault();e.stopPropagation();parent.postMessage(ref,'*');},true);})();</script>'''.replace('REFERENCES',data)
    return ''.join(parser.output)+bridge
