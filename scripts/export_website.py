"""Export public marketing HTML without initializing application data or agents."""
import argparse
import json
import shutil
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contract_web.marketing import register_marketing

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    dest=args.destination.resolve()
    if dest.exists():
        raise SystemExit('Use a fresh output directory; existing files are never replaced.')
    dest.mkdir(parents=True)
    app=FastAPI()
    page=register_marketing(app,ROOT)
    app.add_api_route('/',lambda:page(),methods=['GET'])
    paths=['/','/en']+[p+'/'+s for s in ('security','open-source','harvey-alternative') for p in ('','/en')]+['/robots.txt','/sitemap.xml','/llms.txt']
    with TestClient(app) as client:
        for url in paths:
            response=client.get(url)
            response.raise_for_status()
            file=dest/('index.html' if url=='/' else url.lstrip('/')+('.html' if '.' not in url else ''))
            file.parent.mkdir(parents=True,exist_ok=True)
            body=response.text
            for target in ('/demo','/spaces','/guide','/login'):
                body=body.replace('href="'+target+'"','href="https://agent.tokrace.com'+target+'"')
            file.write_text(body,encoding='utf-8')
    (dest/'static/brand').mkdir(parents=True)
    for name in ('openharvey.css','brand/openharvey.svg','brand/openharvey-social.png'):
        if (ROOT/'static'/name).is_file():shutil.copy2(ROOT/'static'/name,dest/'static'/name)
    config={'cleanUrls':True,'trailingSlash':False,'headers':[{'source':'/(.*)','headers':[
        {'key':'X-Content-Type-Options','value':'nosniff'},
        {'key':'Referrer-Policy','value':'strict-origin-when-cross-origin'},
        {'key':'Content-Security-Policy','value':"default-src 'self'; style-src 'self'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"}]}],
        'redirects':[{'source':'/landing','destination':'/','permanent':True}]}
    (dest/'vercel.json').write_text(json.dumps(config,indent=2)+'\n')
    print(json.dumps({'destination':str(dest),'pages':len(paths)}))

if __name__=='__main__': main()
