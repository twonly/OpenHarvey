---
name: contract-summary
description: 阅读当前完整合同，生成带原文引用的合同摘要并保存为可下载文档。用户要求整份合同概要、核心商务信息或完整摘要时使用；单个条款问答直接查阅原文。
---

# 合同摘要

读取工作目录的 `context.json`，确定主合同与当前会话附件。用原生 `read` 分段读取主合同的全部编号正文；长文件必须继续读取后续行，不能只凭搜索结果概括全文。数字、条件、例外和义务分别以对应原文为准。

按 [摘要模板](references/template.md) 组织内容，用户指定的格式、篇幅优先。保留原文给出的完整引用标记，例如 `【D0123456789ab:B12】`。没有约定或缺少附件时明确说明，不能补造数字或条款。

用原生写文件工具将带引用的 Markdown 正文写入 `summary.md`，再创建短元数据 `summary.json`，避免把长正文嵌入 JSON 时产生引号转义错误：

```json
{
  "kind": "summary",
  "title": "合同摘要",
  "source_hash": "context.json 中主合同的 source_hash",
  "content_file": "summary.md"
}
```

通过原生 `bash` 执行 `python3 <context.json 的 publish_script> summary.json`。脚本只检查结构、引用、原文实际读取记录并保存文件，不调用模型。收到 `saved: true` 后告知用户可在产出物面板预览和下载 Word；失败则根据返回信息补齐，不能声称已保存。
