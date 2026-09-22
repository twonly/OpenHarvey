"""Public product copy paired with owner-supplied, already masked screenshots."""
from html import escape

FEATURES = [
    {'id':'sources','image':'source-traceability.png','size':(2934,1610),
     'zh':('原文比对与高亮，让每个判断找得到出处。','回答与原文并排核对；点击有效引用，联动定位到对应页码与连续段落，并高亮相关条款。看清结论，也看清它从哪里来。','不止回答“是什么”，还能追问“依据在哪一条”。','回答引用联动 PDF 原文，高亮第 16 页相关条款'),
     'en':('Check the finding. See the source.','Compare answers with the original document side by side. Follow valid citations to the relevant page and continuous passages, with highlighted clauses for direct verification.','Move from “What does it say?” to “Where does it say that?”','An answer linked to highlighted clauses on page 16 of the original PDF')},
    {'id':'deliverables','image':'deliverable-preview.png','size':(2940,1602),
     'zh':('产出形式，由你的任务决定。','不局限于固定报告模板。按需生成项目开工会材料、风险审查报告、合同摘要、条款对照、HTML 看板或结构化清单；已保存成果进入产出物区，支持的格式可直接预览、核对和下载。','从一份合同，走到一场开工会、一份风险报告和下一步行动。','项目开工会 HTML 材料在产出物区预览，包含原文引用'),
     'en':('Deliver the format your task needs.','Go beyond a fixed report template: create project kickoff materials, risk review reports, summaries, clause comparisons, HTML dashboards or structured lists. Saved outputs appear in the deliverables pane for preview in supported formats and download.','Turn a contract into a kickoff briefing, a risk report and a next step.','An HTML project kickoff briefing preview with source citations')},
    {'id':'playbooks','image':'risk-playbooks.png','size':(2934,1584),
     'zh':('你的风险清单，你的审查立场。','内置付款、验收、违约责任、解除与结算四类通用示例风险点。复制为个人方案后，按需增删检查项、调整基线；设置甲方、乙方、采购方、供应商等我方立场，让审查围绕本次业务标准展开。','同一份合同，用自己的标准核对，从自己的立场判断。','风险库页面展示公开示例、复制为个人方案及可配置风险项'),
     'en':('Your checklist. Your side of the table.','Start with four illustrative checks covering payment, acceptance, liability and termination. Copy a playbook into your account, adjust checks and baselines, and set your perspective as Party A, Party B, buyer or supplier.','Apply your business standards from the perspective that matters to you.','Risk playbooks with public examples, personal copies and configurable checks')},
    {'id':'skills','image':'custom-skills.png','size':(2940,1584),
     'zh':('三大核心 Skills，开箱即用，也能继续扩展。','预置合同摘要、合同风险审查、条款修改三大核心 Skills。可以复制、调整或新增个人 Skill，把常用步骤、参考资料和交付要求写成可复用指引，让 Agent 按你的方法工作。','把一次好用的方法，变成下一次可以复用的 Skill。','Skills 页面展示条款修改、合同风险审查、合同摘要及新建 Skill 入口'),
     'en':('Three core Skills. Room for your own.','Start with contract summaries, contract risk review and clause revision. Copy, edit or add personal Skills to turn recurring steps, references and delivery requirements into reusable agent instructions.','Turn a useful workflow into a Skill you can use again.','The three built-in Skills and the option to create a personal Skill')},
    {'id':'models','image':'byok-models.png','size':(2930,1550),
     'zh':('先免费体验，再接入自己的模型。','免登录试用默认含 10 次平台任务请求；注册后总额度默认提升至 20 次，包含同一 demo 身份已用次数。支持 BYOK（自带 API Key），配置服务地址与模型 ID，接入兼容 OpenAI 接口的模型服务，也可连接 OrcaRouter。','不绑定单一模型，让任务、预算与偏好决定你的选择。','模型与服务页面展示 OrcaRouter、API 配置及可选模型列表') ,
     'en':('Try it first. Bring your own model next.','The hosted demo defaults to 10 task requests; registration raises the total allowance to 20, including requests already used by the same demo identity. Bring your own API key, endpoint and model IDs for OpenAI-compatible services, or connect OrcaRouter.','Choose a model around your task, budget and preferences.','Model settings with OrcaRouter, API configuration and a model list')},
]


def feature_gallery(en=False, compact=False):
    language='en' if en else 'zh'
    prefix='/en' if en else ''
    items=[]
    for index,feature in enumerate(FEATURES,1):
        title,description,benefit,alt=feature[language]
        image='/static/product/'+feature['image']
        width,height=feature['size']
        level='h3' if compact else 'h2'
        heading=f'<span class="showcase-number">0{index}</span><{level}>{escape(title)}</{level}>'
        picture=f'<img src="{image}" width="{width}" height="{height}" loading="lazy" decoding="async" alt="{escape(alt)}">'
        if compact:
            items.append(f'<a class="showcase-card" href="{prefix}/features#{feature["id"]}">{picture}<div>{heading}</div></a>')
        else:
            caption='Open full-size screenshot ↗' if en else '查看完整截图 ↗'
            items.append(f'<article class="showcase-feature" id="{feature["id"]}"><div class="showcase-copy"><div>{heading}<p class="showcase-benefit">{escape(benefit)}</p></div><p>{escape(description)}</p></div><figure><a href="{image}" target="_blank" rel="noopener">{picture}</a><figcaption>{escape(alt)} · <a href="{image}" target="_blank" rel="noopener">{caption}</a></figcaption></figure></article>')
    return '<div class="showcase-grid">'+''.join(items)+'</div>' if compact else ''.join(items)


def showcase_note(en=False):
    return ('Owner-supplied screenshots show the Chinese workspace; account identifiers are masked in the supplied images. They illustrate the interface, not independently verified review results. Preview availability depends on the saved format, not token-by-token rendering of every file. Trial requests count tasks, not internal model calls; allowances may change and the workspace shows your current balance. BYOK requires a compatible API and tool-calling support; provider charges and sandbox limits still apply.' if en else
            '截图由项目方提供，账号标识已在供图中打码；展示的是产品界面，不作为审查正确性或任务全部完成的证明。预览以已保存文件与支持格式为准，并非所有文件都逐字实时渲染。免费额度按任务请求计数，不等于底层模型调用次数；额度可能调整，以工作台显示为准。BYOK 需满足接口兼容与工具调用要求，模型费用由对应供应商收取，仍受沙箱资源限制。')


def review_updates(en=False):
    def t(zh,english):return english if en else zh
    return f'''<section class="section release-features" id="latest"><p class="eyebrow">NEW / MEMORY + DOCUMENT REVIEW</p><h2>{t('记住你的偏好，和 Agent 一起审改。','Your preferences, remembered. Your revisions, in context.')}</h2><p class="intro">{t('少重复交代工作习惯，把修改、批注和原文放在一起核对。','Spend less time repeating preferences. Review changes and comments alongside the contract.')}</p><div class="release-grid"><article id="memory" class="release-card"><span class="release-tag">MEMORY · LABS</span><h3>{t('由你掌控的个人记忆','Personal memory you control')}</h3><p>{t('开启后，可以让 Agent 记住长期工作偏好；也可以自己添加、编辑、删除，或随时关闭。后续任务会参考已保存的偏好，当前指令优先。','Opt in to let the agent remember long-term working preferences. Add, edit or delete them yourself, or turn memory off. Later tasks use saved preferences; your current instructions take priority.')}</p><blockquote>{t('“记住：先给我结论，再列依据，尽量用简洁中文。”','“Remember: lead with the conclusion, then cite the evidence. Keep it concise.”')}</blockquote><p class="fine">{t('用于个人工作与表达偏好；合同金额、条款事实和审查依据仍来自本次材料。关闭或删除记忆不会改写旧对话。','For working and communication preferences. Contract facts and review evidence stay in the current materials. Disabling or deleting memory does not rewrite past conversations.')}</p><a href="/labs">{t('管理个人记忆 ↗','Manage memory ↗')}</a></article><article id="redline" class="release-card"><span class="release-tag">DOCX REVIEW · {t('灰度开放','LIMITED ROLLOUT')}</span><h3>{t('在原文里修改，在上下文中审阅','Edit the contract. Review in context.')}</h3><p>{t('圈选条款交给 Agent，明确修改后直接保存为待审修订。点击修订或批注定位正文，逐项接受或拒绝修改，独立回复与解决批注。','Select a clause and instruct the agent to edit it. Explicit edits are saved as pending tracked changes. Navigate between changes, comments and their text; accept or reject changes and reply to or resolve comments separately.')}</p><blockquote>{t('“将选中的付款期限改为 60 天，其他内容保持不变。”','“Change the selected payment term to 60 days. Keep the rest unchanged.”')}</blockquote><p>{t('工作稿目录双向定位 · 自动保存 · 命名重要版本 · 历史恢复 · 修订版与清洁版下载','Linked document outline · Autosave · Named milestones · Version restore · Revised and clean DOCX downloads')}</p><p class="fine">{t('当前面向已启用账号的 DOCX 单人审改。上传原件保留；清洁版需先处理全部待审修订。PDF 支持阅读、分析和建议，不提供原生 Word 修订。复杂排版兼容性仍在验证。','Single-user DOCX review for enabled accounts. The uploaded original is retained; resolve all pending changes before clean export. PDFs support reading, analysis and suggestions, not native Word redlining. Complex layout compatibility is still being evaluated.')}</p><a href="/spaces">{t('进入合同工作台 ↗','Open the workspace ↗')}</a></article></div></section>'''
