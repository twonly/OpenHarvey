"""Repeatable engine smoke test on synthetic documents, not visual certification."""
import argparse, asyncio, json, subprocess
from collections import Counter
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import hashlib

ROOT=Path(__file__).resolve().parents[1]
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
async def engine(source,action,**kw):
    p=await asyncio.create_subprocess_exec('node',str(ROOT/'scripts/superdoc-engine.mjs'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    out,err=await p.communicate(json.dumps({'source':str(source),'action':action,**kw}).encode())
    r=json.loads(out)
    if not r.get('ok'):raise ValueError(r)
    return r

def structure(path):
    with ZipFile(path) as z:
        root=ET.fromstring(z.read('word/document.xml'))
        counts=Counter(e.tag.removeprefix(W) for e in root.iter() if e.tag in {W+x for x in ('tbl','tr','tc','sectPr','drawing')})
        media=sorted(hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('word/media/') and not n.endswith('/'))
        marginal=sorted(''.join(ET.fromstring(z.read(n)).itertext()) for n in z.namelist() if n.startswith(('word/header','word/footer')) and n.endswith('.xml'))
        return {'counts':dict(counts),'media':media,'marginal':marginal}

async def main(folder):
    results=[]
    for source in sorted(folder.glob('*.docx')):
        if source.name.endswith(('-tracked.docx','-accepted.docx','-seed.docx')):continue
        try:
            original=await engine(source,'inspect')
            out=folder/(source.stem+'-tracked.docx');accepted=folder/(source.stem+'-accepted.docx')
            # Include an existing tracked revision before the second review round.
            if source.stem=='bilingual':
                seed=folder/(source.stem+'-seed.docx')
                await engine(source,'apply',output=str(seed),author={'name':'Prior reviewer','email':'prior@example.test'},changes=[{'quote':'Governing Law','replacement':'Applicable Law'}])
                source=seed;original=await engine(source,'inspect')
            await engine(source,'apply',output=str(out),author={'name':'Contract Agent','email':'agent@example.test'},changes=[{'quote':'30 天','replacement':'60 天'}])
            revised=await engine(out,'inspect')
            assert revised['text']==original['text'].replace('30 天','60 天'), 'Unexpected text change'
            assert structure(source)==structure(out),'Document structures changed'
            assert len(revised['comments'])==len(original['comments']),'Comments lost'
            assert len(revised['changes'])>len(original['changes']),'Native revisions absent'
            await engine(out,'decide',output=str(accepted),decision='accept',ids=[c['id'] for c in revised['changes']])
            final=await engine(accepted,'inspect');assert not final['changes'];assert final['text']==revised['text']
            results.append({'file':source.name,'ok':True,'revisions':len(revised['changes']),'comments':len(revised['comments'])})
        except Exception as error:results.append({'file':source.name,'ok':False,'error':str(error)})
    (folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps(results,ensure_ascii=False,indent=2))
    if len(results)<12 or not all(r['ok'] for r in results):raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='.cache/redline-corpus');a=p.parse_args();asyncio.run(main(Path(a.output).resolve()))
