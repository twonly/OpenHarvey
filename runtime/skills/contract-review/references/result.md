# 风险报告输出

写入 JSON 对象：

```json
{
  "kind": "review",
  "title": "风险审查报告",
  "source_hash": "主合同内容哈希",
  "perspective": "乙方（或用户明确指定的主体与角色）",
  "content_file": "review.md",
  "findings": [
    {
      "risk_id": "风险库中的真实编号",
      "verdict": "命中",
      "severity": "高",
      "applicable": true,
      "reason": "结合公司基线、具体条款、条件及例外说明理由",
      "evidence": [
        {
          "document_id": "context.json 中的文档 id（不含 D 前缀）",
          "source_hash": "对应文档内容哈希",
          "block_id": "B12",
          "quote": "对应原文段落中的逐字引文，不含引用标记"
        }
      ]
    }
  ]
}
```

所有启用风险点均需输出，不能只保存命中项。缺失型风险以涉及该义务或责任的原文作为上下文证据，并说明已查完整合同、未发现何种等效保护。没有材料支撑判断时使用“信息不足”。不适用项和信息不足项可无证据，但必须说明原因。每条具体正文的引用格式保留为 `【D文档ID:B编号】`。
