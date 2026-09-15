"""Export public marketing HTML without initializing application data or agents."""
import argparse
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contract_web.marketing import register_marketing

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_PATHS = ['/', '/en'] + [p+'/'+s for s in ('security','open-source','harvey-alternative','features') for p in ('','/en')]
WORKBENCH_PATHS = ['/connectors','/demo','/spaces','/guide','/login','/agent','/model','/config','/traces','/ops','/ops/:path*','/skills','/risks','/members','/organization','/health','/api/:path*','/auth/:path*','/orca/:path*','/trial-model/:path*','/static/:path*']

def hosting_config(workbench_origin):
    origin=workbench_origin.rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('Workbench origin must be an HTTPS origin without credentials or a path.')
    policy="default-src 'self'; style-src 'self'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    # Marketing CSP must not override the workbench or sandboxed artifact policies.
    headers=[{'source':'/(.*)','headers':[
        {'key':'X-Content-Type-Options','value':'nosniff'},
        {'key':'Referrer-Policy','value':'strict-origin-when-cross-origin'}]}]
    headers += [{'source':path,'headers':[{'key':'Content-Security-Policy','value':policy}]} for path in PUBLIC_PATHS]
    headers += [{'source':path,'headers':[
        {'key':'Cache-Control','value':'no-store'},
        {'key':'CDN-Cache-Control','value':'no-store'},
        {'key':'x-vercel-enable-rewrite-caching','value':'0'}]} for path in WORKBENCH_PATHS]
    return {'cleanUrls':True,'trailingSlash':False,'headers':headers,
        'rewrites':[{'source':path,'destination':origin+path} for path in WORKBENCH_PATHS],
        'redirects':[{'source':'/landing','destination':'/','permanent':True}]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('destination',type=Path)
    parser.add_argument('--workbench-origin',required=True,help='HTTPS backend origin; public links stay on the website domain.')
    args=parser.parse_args()
    config=hosting_config(args.workbench_origin)
    dest=args.destination.resolve()
    if dest.exists():
        raise SystemExit('Use a fresh output directory; existing files are never replaced.')
    dest.mkdir(parents=True)
    app=FastAPI()
    page=register_marketing(app,ROOT)
    app.add_api_route('/',lambda:page(),methods=['GET'])
    paths=PUBLIC_PATHS+['/robots.txt','/sitemap.xml','/llms.txt']
    with TestClient(app) as client:
        for url in paths:
            response=client.get(url)
            response.raise_for_status()
            file=dest/('index.html' if url=='/' else url.lstrip('/')+('.html' if '.' not in url else ''))
            file.parent.mkdir(parents=True,exist_ok=True)
            body=response.text
            file.write_text(body,encoding='utf-8')
    (dest/'static/brand').mkdir(parents=True)
    for name in ('site-telemetry.js','openharvey.css','showcase.css','brand/openharvey.svg','brand/openharvey-social.png','brand/github.svg','brand/google.svg'):
        if (ROOT/'static'/name).is_file():shutil.copy2(ROOT/'static'/name,dest/'static'/name)
    shutil.copytree(ROOT/'static/product',dest/'static/product')
    (dest/'vercel.json').write_text(json.dumps(config,indent=2)+'\n')
    print(json.dumps({'destination':str(dest),'pages':len(paths)}))

if __name__=='__main__': main()
