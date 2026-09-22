#!/usr/bin/env python3
"""Submit an actual JSON report using this thread's save-only capability."""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise ValueError("用法：python3 publish.py 当前目录中的报告.json")
    root = Path.cwd()
    source = (root / sys.argv[1]).resolve()
    if not source.is_relative_to(root.resolve()):
        raise ValueError("报告必须在当前对话工作目录中")
    body = json.loads(source.read_bytes())
    # Keep long Markdown outside JSON so the model need not escape every quote.
    if isinstance(body, dict) and body.get("content_file"):
        markdown = (root / body.pop("content_file")).resolve()
        if not markdown.is_relative_to(root.resolve()):
            raise ValueError("正文文件必须在当前对话目录中")
        body["content"] = markdown.read_text(encoding="utf-8")
    content = json.dumps(body, ensure_ascii=False).encode()
    context = json.loads((root / "context.json").read_text())
    token = (root / ".publish-token").read_text().strip()
    req = urllib.request.Request(context["save_url"], data=content,
          headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    # Runtime-to-Web calls must not use an inherited network proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=180) as response:
            print(response.read().decode())
    except urllib.error.HTTPError as exc:
        data = json.loads(exc.read())
        raise ValueError(data.get("detail", "保存失败")) from None


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"saved": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
