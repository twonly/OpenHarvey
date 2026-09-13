---
name: contract-review
description: 对照当前选择的风险点方案逐项审查当前完整合同，输出有原文证据的风险清单和可下载报告。用户要求整份合同风险审查时使用；状态询问和单条款解释无需完整审查。
---

# 合同风险审查

读取当前工作目录 `context.json`。未明确立场时使用 context.json 中的 default_perspective；用户本次或对话中已确认的主体和角色优先。我方身份无法唯一确定且影响判断时，用当前聊天中的原生提问补齐后继续。

读取 context.json 指定的风险库文件，以及主合同全部编号正文。用原生 `read` 的 offset/limit 分段读长文件，搜索只作定位；查找不到关键词不能证明缺少保护条款。需要的附件未提供时记录信息不足。

逐项处理全部启用的风险点，遵循原库的适用范围、方案基线和判定口径。结论只用“命中／未命中／信息不足”；不适用项用“未命中”、`applicable: false` 并说明原因。缺失与跨条款判断须建立在全文阅读及等效保护检查之上。证据引用应保留条件和例外。

按 [输出格式](references/result.md) 将 Markdown 报告写 `review.md`，在 `review.json` 用 `content_file: "review.md"` 引用它，并填写 findings。不要将长 Markdown 嵌入 JSON 字符串，以免引号转义错误。每个启用风险点在两者中均出现，报告汇总数量从实际清单统计。可按类别组织工作并使用原生 Todo，任务是否完成以实际结果为准。

执行 `python3 <context.json 的 publish_script> review.json`。脚本只校验结构、风险项覆盖、引用及原文实际读取记录，并保存真实文件。收到 `saved: true` 后说明已保存；否则根据具体错误补齐，不得虚构保存回执。报告中的分析由当前 OpenCode Agent 完成，不调用另一套模型脚本或额外 grader。
