# 保存其他格式的产出物

支持 md、html、txt、json、csv、svg。用户要求某种格式时保存真正的对应文件，不把 Markdown 改后缀。先写正文文件，再写提交 JSON，通过 context.json 中 publish_script 发布：

```json
{"kind":"document","title":"合同要点看板","format":"html","source_hash":"context.json 中主合同的 source_hash","content_file":"drafts/dashboard.html"}
```

HTML、SVG 可以包含内联样式与内联脚本，用于图表和简单交互。预览在隔离环境中运行，不能请求外部资源、访问工作台或提交表单；不要依赖 CDN、外部图片、网络或浏览器存储。提供完整、自包含文件。

真实合同信息先读取对应原文，使用原文自带的【D文档ID:B编号】。缺失材料如实说明。完整摘要仍用 kind=summary，完整风险审查仍用 kind=review，并遵守相应 Skill 的全文阅读、引用、findings 要求；可指定 format=html 或 txt。结构化条款修改稿用 revision 模板和默认 md。

Markdown 自动提供同内容 Word 下载；其他格式提供原格式下载，不自动转换成 Word。保存回执中的 artifact_id 是正式产出物；工作台会自动列出它。用户只需看到标题和保存结果，不要输出本机绝对路径。
