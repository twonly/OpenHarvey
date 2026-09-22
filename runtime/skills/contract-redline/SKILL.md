---
name: contract-redline
description: 根据用户要求和原文起草并保存条款修改稿，无须先完成整份风险审查。
---

# 条款修改

读取当前目录 context.json 和用户指定条款的编号原文，确认拟修改的范围与目的。沿用用户已确认的我方立场；只有主体不明确且影响改写时才在会话中询问。

根据本次明确要求、原文和已确认的风险处置意见提出替换条款。保留原文引用、关键条件与例外；说明每条修改的业务原因。未经请求不覆盖源合同。

如果 context.json.redline.enabled=true 且目标 DOCX 在 redline.documents 中，读取 redline.guide。先读取最新工作副本，按已声明能力直接写入待审修订，使用保存回执中的实际差异和版本下载链接交付；不默认追加 inspect、diff、export；不再输出一份替代原生修订的条款对照稿。用户手改、其他人的修订及批注都以最新工作版本为准。结构能力不支持时说明限制，不试探性写入或查找产品源码。

其他情况读取 context.json 的 revision_format，按其中格式生成条款对照 JSON。通过 context.json 的 publish_script 保存。只有实际收到 saved: true 回执后才告知用户修改稿已保存；有真实下载回执才能说可下载。失败时依据错误补齐。对用户使用文件名和业务结果，不解释内部脚本。
