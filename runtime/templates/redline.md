# DOCX 工作副本工具

仅 context.json.redline.enabled=true 且目标在 redline.documents 中时使用。
通过现有 publish_script 传输 JSON，不新增模型或编排。kind="redline" 是文档工具请求，不是 Markdown 报告。

## 读取当前合同

使用原生 write 工具在当前对话目录写 request.json，再单独执行 `python3 <publish_script> request.json`。不要把 mkdir、printf、Python heredoc 和发布命令串成一条 bash：复合命令会触发额外权限询问，且没有必要。沿用现有谨慎模式的写入权限，不绕过审批。

```json
{"kind":"redline","action":"inspect","document_id":"目标文档ID"}
```

返回 version.id、snapshot.text、snapshot.changes、snapshot.comments 和 capabilities。默认不返回历史版本及旧操作；确实需要历史时传 history=true。text 是包含待审建议的工作文本，不代表双方已同意。原始 source_hash 与工作版本不同；引用工作内容时说明工作版本，不伪造上传原件的 B 编号。

定位重复条款：
```json
{"kind":"redline","action":"find","document_id":"目标文档ID","quote":"逐字原文"}
```
搜索与 snapshot.text 均使用可见文本（含待审新增、不含待审删除）；没有匹配返回 total=0，这不代表跨段落能力检测。只有原文重复、需要明确块位置时才调用 find；原文唯一时可直接 apply。读取匹配项 address.nodeId 和 snippet；修改时使用 block_id 和 context 缩小范围。页面序号或 DOM 位置不是写入地址。

## 直接写入待审修订

```json
{
  "kind":"redline","action":"apply","document_id":"目标文档ID",
  "base_version":"刚读取的version.id",
  "summary":"付款期限调整为60天",
  "changes":[{"quote":"付款期限为30天。","replacement":"付款期限为60天。","reason":"按用户要求调整付款期限","type":"replace"}]
}
```

- type 支持 replace、delete、insert_before、insert_after；插入以 quote 为锚点。
- changes 可附 block_id、context、真实来源 sources 和已保存报告的 risk_id。不要编造来源。
- 一次请求全部成功才保存新版本；失败不会保存一半。
- 操作成功返回 saved=true、version_id、实际 diff、pending_changes 和 download_url。下载链接指向此次已保存的不可变 DOCX 版本，包含原生修订和批注；可直接交付，不必再 inspect、diff、export。diff 是真实正文变化，不证明排版保真。
- Agent 请求不用填写 request_id，后端按当前对话、基础版本和输入自动生成幂等标识。不要调用 uuidgen、Python 或 shell 生成 ID。同一操作不确定时重试完全相同的请求；内容或版本变化会生成新标识。显式传入 request_id 的旧客户端仍可用。
- 409 表示版本或编辑状态冲突：重新 inspect 并比较目标条款，只在目标或上下文改变时重写建议；不能盲目替换 base_version 重放旧改动。不能仅凭版本号变化声称用户修改了正文。持续冲突时保留已保存结果，说明正在等待同步，不循环追逐版本。
- 对同一待审建议换表述时，可在 change.supersedes 提供明确的旧修订 ID。引擎先在副本拒绝这些旧建议，再定位恢复后的 quote 写入新建议。只针对用户要求替换的建议，不撤销其他修改。
- 只解释风险或询问事实时，使用 inspect/find，不执行 apply。

## 当前能力边界

- capabilities.tracked_paragraph_merge / tracked_paragraph_split 当前为 false。SuperDoc 1.46.3 的跨段落修订未通过 DOCX 接受／拒绝往返验证。用户明确要求合并或拆分段落时，说明此限制并给出建议措辞，不执行试探性写入。
- 不把“整段删除文字”当作删除段落；不要用先改一段、再删除另一段绕过结构能力限制。
- UNSUPPORTED_* 表示能力缺口，停止该操作并清楚说明未修改。不要搜索产品源码、探测其他无关条款或反复撤销重做。定位失败可以针对最新目标重新读取一次；相同输入重复失败不再重试。

## 修订和批注

接受／拒绝用户明确选定的修订：action="decide"，decision="accept" 或 "reject"，ids 为最新 snapshot.changes 的 ID 列表。保留其他人的未决修改，不能自行全部接受。

批注：action="comment"；operation="create" 带 quote、text；reply 带 id、text；resolve/reopen 带 id。均带 base_version；request_id 由后端生成。

## 发布

```json
{"kind":"redline","action":"export","document_id":"目标文档ID","base_version":"要交付的已保存version.id","clean":false}
```

仅用户要求清洁版、单独产出物或重新发布时使用 export。按指定已保存版本生成，不占用编辑权，也不要求其仍是最新版本；向用户说明这是哪个保存版本，不声称包含后续编辑。

clean=false 保留 Word 原生修订及批注。clean=true 要求不存在未决修订，只在交付副本中清理批注，工作版本中的讨论仍保留。不能默默接受修订来绕过清洁版检查。

差异检查：action="diff"，before_version 为修改前版本，after_version 为保存回执版本；返回工作文本差异（不代表排版差异）。读取操作不需要 request_id，E2B 传输自动防止读缓存。

默认交付顺序：读取当前目标 → 一次 apply → 阅读回执中的实际 diff → 展示已保存结果和 download_url。只有回执显示异常或用户要求额外核对时才继续读取；不要为了重复确认已由回执证明的事实增加工具轮次。不要把生成 JSON、引擎执行或 pending 说成已交付。无需先做全合同风险审查，也不增加审批或 grader。

一次接受或拒绝是本合同的处置，不自动写入长期 Memory。
