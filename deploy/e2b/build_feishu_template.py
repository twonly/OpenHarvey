"""Build a separate test template; never update the production alias."""
import os
from pathlib import Path
from e2b import Template, default_build_logger

ROOT=Path(__file__).resolve().parents[2]
if __name__=='__main__':
    if not os.environ.get('E2B_API_KEY'):
        os.environ['E2B_API_KEY']=(ROOT/'data/e2b-debug/secrets/e2b.key').read_text().strip()
    template=(Template().from_template('opencode')
        .run_cmd('npm install -g opencode-ai@1.16.2 && npm install -g --prefix /opt/feishu @larksuite/cli@1.0.76',user='root')
        .run_cmd('mkdir -p /opt/feishu/skills && for name in lark-shared lark-doc lark-wiki lark-base; do mkdir -p /opt/feishu/skills/$name; /opt/feishu/bin/lark-cli skills read $name > /opt/feishu/skills/$name/SKILL.md; done',user='root')
        .run_cmd('opencode --version && /opt/feishu/bin/lark-cli --version'))
    result=Template.build(template,'contract-opencode-feishu-dev-1-16-2',cpu_count=2,memory_mb=2048,on_build_logs=default_build_logger())
    print(result)
