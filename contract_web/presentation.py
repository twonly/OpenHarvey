"""Public execution receipts. Native tool inputs/outputs stay in OpenCode."""
import re
from pathlib import PurePosixPath
from .report_processing import merge_citations


class PublicView:
    def __init__(self, paths=None, locale='zh-CN'):
        self.locale = 'en' if locale == 'en' else 'zh-CN'
        self.paths = paths or {}
        self.text_parts = {}
        self.suppressed_messages = set()

    def label(self, text, **values):
        labels = {
            '工作文件': 'Working file', '附件': 'Attachment',
            'Skill 参考资料': 'Skill references', '本次对话': 'This conversation', '公司资料': 'Company materials',
            '第 {start}–{end} 行': 'Lines {start}–{end}', '从第 {start} 行读取': 'Read from line {start}',
            '查找：': 'Find: ', '搜索：': 'Search: ', '执行文件处理命令': 'Run file-processing command',
            '操作触及当前对话允许范围外的目录，未执行。请在当前对话目录使用材料索引中的准确路径。':
                'This operation was not run because it accessed a directory outside this conversation. Use the exact material path in the current conversation directory.',
            '该操作被当前权限规则禁止，未执行。': 'This operation was not run because the current permission rules prohibit it.',
            '你已拒绝本次操作，未执行。': 'You rejected this operation; it was not run.',
        }
        return (labels.get(text, text) if self.locale == 'en' else text).format(**values)

    def text(self, value):
        value = str(value or "")
        # HTTP URLs are sources, not local paths (the s:/ in https:/ also
        # resembles a Windows drive). Apply path aliases only outside URLs.
        pieces = re.split(r'(https?://[^\s\"\'<>，。；）】`)]+)', value, flags=re.I)
        return merge_citations(''.join(piece if i % 2 else self.local_paths(piece)
                                      for i, piece in enumerate(pieces)))

    def local_paths(self, value):
        for path, label in sorted(self.paths.items(), key=lambda item: -len(item[0])):
            value = value.replace(path, label)
            if path.startswith("/"):
                value = value.replace(path.lstrip("/"), label)
        value = re.sub(r"(?:file://)?/(?:private|var|Users|home|tmp|work|sources|opt)(?:/[^\s\"'<>，。；）】`)]*)?|[A-Za-z]:[\\/][^\s\"'<>]+",
                       lambda m: self.label('工作文件') + "/" + re.split(r"[/\\]", m[0].rstrip("/"))[-1], value)
        return value

    def request(self, request):
        # Permission replies use the native request ID; never authorize a rewritten command.
        result={k: self.clean(v) for k, v in request.items() if k != "metadata"}
        metadata=request.get('metadata')
        description=metadata.get('description') if isinstance(metadata,dict) else None
        if isinstance(description,str) and description.strip():result['description']=self.text(description)[:240]
        return result

    def clean(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, dict):
            return {k: self.clean(v) for k, v in value.items()}
        return value

    def info(self, info):
        return self.clean({k: v for k, v in info.items() if k in {
            "id", "sessionID", "role", "time", "finish", "error", "parentID", "summary", "mode"}})

    def part(self, part):
        base = {k: part[k] for k in ("id", "messageID", "sessionID", "type") if k in part}
        if part.get("type") == "text":
            self.text_parts[part.get("id")] = dict(part)
            return {**base, "text": self.text(part.get("text")),
                    **({'synthetic':True} if part.get('synthetic') is True else {}),
                    **({'metadata':{'compaction_continue':True}} if (part.get('metadata') or {}).get('compaction_continue') is True else {})}
        if part.get("type") == "file":
            return {**base, "filename": PurePosixPath(part.get("filename", self.label('附件'))).name}
        state, tool = part.get("state", {}), part.get("tool", "")
        inp = state.get("input", {})
        target = inp.get("filePath") or inp.get("path") or inp.get("name") or ""
        details = []
        if target:
            details.append(self.text(target))
        if tool == "read" and isinstance(inp.get("offset", 1), int):
            start, count = inp.get("offset", 1), inp.get("limit")
            details.append(self.label('第 {start}–{end} 行', start=start, end=start+count-1) if isinstance(count, int) else self.label('从第 {start} 行读取', start=start))
        if tool in {"grep", "glob"} and inp.get("pattern"):
            details.append(self.label('查找：') + self.text(inp["pattern"])[:200])
        if tool == "websearch" and inp.get("query"):
            details.append(self.label('搜索：') + self.text(inp["query"])[:200])
        if tool == "webfetch" and inp.get("url"):
            details.append(self.text(inp["url"])[:600])
        if tool == "bash":
            details.append(self.text(inp.get("description") or self.label('执行文件处理命令')))
        if tool == "todowrite":
            details += [self.text(t.get("content")) for t in inp.get("todos", []) if isinstance(t, dict)]
        if state.get("error"):
            error = state["error"]
            if "The user has specified a rule" in error:
                error = self.label("操作触及当前对话允许范围外的目录，未执行。请在当前对话目录使用材料索引中的准确路径。"
                         if '"permission":"external_directory"' in error.replace(" ", "") else
                         "该操作被当前权限规则禁止，未执行。")
            elif "user rejected" in error.lower():
                error = self.label("你已拒绝本次操作，未执行。")
            details.append(self.text(error)[:600])
        # No raw input, stdout, file URLs, or absolute-path metadata in browser responses.
        return {**base, "tool": tool, "state": {"status": state.get("status"),
                "time": state.get("time", {}), "detail": " · ".join(details)}}
