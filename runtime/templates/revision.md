# 条款修改稿格式

只修改用户指定的条款，保留其他条款和原始文件。读取对应编号原文后，使用原生工具写 `revision.json`：

```json
{
  "kind": "revision",
  "title": "付款条款修改稿",
  "source_hash": "context.json 中主合同的 source_hash",
  "changes": [{
    "document_id": "要修改的文档 ID",
    "block_id": "B4",
    "quote": "逐字复制要替换的原条款",
    "replacement": "完整建议条款",
    "reason": "与用户修改要求的对应关系"
  }]
}
```

执行 `python3 <context.json 的 publish_script> revision.json`。Web 按同一 changes 生成原条款、建议条款和理由对照，保存 Markdown 与 Word，返回真实回执。此功能不生成 Word 原生修订标记，也不覆盖上传原件。
