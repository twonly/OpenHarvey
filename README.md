# OpenHarvey

**OpenHarvey (Open Harvey) is an open-source Harvey alternative for contract review and tender workflows.**

Inspect source-linked findings, configure your own review playbooks and choose a self-hosting setup. [Explore the Harvey alternative guide](https://openharvey.com/en/harvey-alternative) for a practical workflow, deployment options and operating costs. OpenHarvey is an independent project, not affiliated with Harvey, and does not claim feature parity.

[中文说明](README.zh-CN.md) · [Website](https://openharvey.com) · [English website](https://openharvey.com/en) · [Try the workspace](https://openharvey.com/demo) · [Deployment](docs/deployment.md)

OpenHarvey connects source documents, conversations and saved deliverables. It is built around the structure of contract work: clauses, attachments, evidence, review playbooks and revisions.

## Why a dedicated workspace?

- **Document-centered work.** Organize the primary agreement, tender documents, attachments and conversations in one contract workspace.
- **Trace findings to sources.** Follow valid citations to highlighted pages or paragraphs. Read original text and outputs side by side.
- **Configurable review.** Bring your own Skills, risk playbooks, party perspective and model settings.
- **Flexible deliverables.** Save summaries, risk reports, clause comparisons and supported custom artifacts, including Markdown, HTML, text, JSON, CSV and SVG. Summary/review/revision workflows also generate Word files. HTML previews run in a restricted iframe.
- **Native agents.** OpenCode handles tools, Skills, sessions and permissions. The application adds document context, navigation, persistence and delivery receipts.
- **Sandbox execution.** Cloud mode runs agents in E2B. Application permissions govern account and document access. Self-hosting the web application does not automatically replace external sandbox or model services.

The website and workspace interface support Chinese and English. Existing documents, examples and generated reports retain their original language. English-contract quality requires separate evaluation.


## What’s new: Memory and DOCX review

- **Personal memory you control:** opt in under Labs, ask the agent to remember long-term preferences, or add, edit and delete them yourself. Current instructions take priority; contract facts remain grounded in current documents.
- **Review with the agent in the contract:** select a clause, request an edit and save it as native pending tracked changes. Changes and comments link to their text; accepting a change and resolving a comment are separate decisions.
- **Keep your place and your history:** linked heading navigation, autosave, grouped save history, named milestones and restore-as-new-version. Preserve the uploaded original and download revised or clean DOCX files.

DOCX review is a **limited rollout for enabled accounts**, built with SuperDoc 1.46.3 on the AGPL route. Single-user editing only; PDFs remain available for reading, analysis and suggestions. Clean export requires resolving pending changes. Complex layout fidelity and complete Word/WPS accept/reject compatibility are still under evaluation.

[Feature details](https://openharvey.com/en/features#latest) · [Setup and boundaries](docs/memory-and-review.md)

## Five product highlights

**See the evidence. Deliver the work.** [Explore the product with full-size screenshots](https://openharvey.com/en/features). The screenshots below show the Chinese workspace; account identifiers are masked in the supplied images.

### 1. Compare findings with highlighted source evidence

Read answers, reports and source documents side by side. Follow valid citations to the relevant page and continuous passages, with highlighted clauses for direct verification. Move from “What does it say?” to “Where does it say that?”

![An answer linked to highlighted clauses in the original PDF](static/product/source-traceability.png)

### 2. Deliver the format your task needs

Go beyond fixed report templates: ask for project kickoff materials, risk review reports, summaries, clause comparisons, HTML dashboards or structured lists. Saved outputs appear in the deliverables pane for supported-format previews and download—not token-by-token rendering of every file type.

Example prompt: **“Create an HTML project kickoff briefing from this tender. Focus on customer needs, delivery scope, acceptance conditions and open questions. Keep source citations.”**

![An HTML kickoff briefing displayed in the deliverables pane with source citations](static/product/deliverable-preview.png)

### 3. Your risk checklist and your perspective

Start with four illustrative checks covering payment, acceptance, liability and termination. Copy a playbook into your account, customize checks and baselines, and set your perspective as Party A, Party B, buyer or supplier.

Example prompt: **“We are the supplier. Review this contract against my selected playbook, with source evidence, risk explanations and proposed revisions for each finding.”**

![Public risk examples and configurable personal playbooks](static/product/risk-playbooks.png)

### 4. Three core Skills, with room for your own

Built-in Skills cover **contract summaries, contract risk review and clause revision**. Copy, edit or add personal Skills to turn recurring steps, references and delivery requirements into reusable agent instructions.

![The three built-in Skills and personal Skill creation](static/product/custom-skills.png)

### 5. Free trial + BYOK, without a single-model lock-in

The hosted demo defaults to **10 task requests**. Registration raises the total allowance to **20**, including requests already used by the same demo identity—not an additional 20. These count task requests, not internal model calls. Current balances and limits are shown in the workspace.

**Bring your own API key**, endpoint and model IDs for OpenAI-compatible services, or connect OrcaRouter. Compatibility and tool-calling support determine which models work; provider charges and sandbox limits still apply.

![BYOK provider configuration, OrcaRouter and multiple model choices](static/product/byok-models.png)

These owner-supplied screenshots illustrate the interface, not independently verified review results or proof that a displayed task fully completed. The underlying business documents and account data are not distributed. Sample risk baselines are fictional examples, not universal legal standards. English prompts here illustrate task intent; full English-task evaluation remains on the roadmap.

## Quick start: local development

Requirements: Python 3.12, Node.js 22 and OpenCode 1.16.2. Local process mode is for a trusted single-user machine; it does not provide OS-level multi-user isolation.

```sh
git clone https://github.com/twonly/OpenHarvey.git
cd OpenHarvey
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
npm run build:redline
npm install -g opencode-ai@1.16.2
export CW_DATA_DIR="$(mktemp -d /tmp/openharvey-data.XXXXXX)"
export CW_SANDBOX_BACKEND=local
export CW_SECURE_COOKIE=0
.venv/bin/python -m contract_web.cli add-user admin
.venv/bin/python -m contract_web.cli init-admin admin
.venv/bin/python -m uvicorn contract_web.app:create_app --factory --host 127.0.0.1 --port 8080
```

For persistent use, replace the temporary `CW_DATA_DIR` with a stable directory **outside the checkout**. Open `/spaces`, use the locally provisioned administrator login and configure a model in Settings → Models and services. Model and sandbox use may incur provider charges. A successful web health check is not proof of a working model or sandbox.

See [deployment instructions](docs/deployment.md) for explicit local runtime setup and E2B cloud deployment. Email/OAuth registration requires your own Supabase project; local administrator login does not.

## Feishu / Lark: company knowledge and business updates

Choose Feishu or Lark in **Connectors**, then create the app and authorize your account through the official website. No access-token copying is required. App permissions, publication and organization approval still apply.

- **Channel contract review:** find sales policies and compare payment terms, authorization scope and rebates with the contract’s direct or channel sales context, citing actual sources.
- **Tender preparation:** combine tender requirements with accessible product and delivery knowledge to prepare response points, gaps and clarification lists; save a shared document when requested.
- **Risk reports and contract registers:** create a report and return its real link; read Base fields before creating or updating the specified records.
- **Collaboration:** with additional contact-search and messaging consent, find recipients and send messages as the user only when explicitly requested.

The control plane manages per-account credentials and refresh. OpenCode calls the official CLI directly from each E2B sandbox. Only access tokens enter the owning sandbox; app secrets and refresh tokens remain on the control plane. Feishu document and Base workflows have live end-to-end evidence; Lark international and messaging still require live-account acceptance. A dedicated CRM connector is not included.

[Setup, permissions and deployment](docs/feishu-lark.md)


## Architecture

```text
Browser: source reader + agent chat + deliverable preview
                       |
FastAPI: identity, ownership, documents, playbooks, artifact delivery
       |                                     |
SQLite + files                       OpenCode runtime
sources / outputs / checkpoints     local development or E2B sandbox
                                             |
                                   selected model provider
```

Input formats: DOCX, text PDF, Markdown and TXT. Scanned PDFs require OCR before upload. Original document IDs and hashes keep citations tied to their sources. Sandboxes may be shared by conversations in the same contract workspace; conversation material scopes are application policies, not separate OS isolation.

## Development

```sh
.venv/bin/python -m unittest discover -s tests -q
node --test tests/frontend.test.mjs
```

Tests use fictional fixtures and mocked runtime paths unless explicitly documented otherwise. They do not establish legal accuracy, production security certification or English-language quality.

Public code is AGPL-3.0-only. Model providers, E2B, Supabase and OpenCode are separate projects/services with their own terms and licenses. See [NOTICE](NOTICE), [SECURITY](SECURITY.md) and [CONTRIBUTING](CONTRIBUTING.md).

## Roadmap

- English workspace UI, stored language preferences and English task evaluation.
- Easier first-time model and sandbox setup.
- Reproducible evaluations using public or fictional documents.
- More reusable review playbooks and deliverable examples.

OpenHarvey is an independent project. It is not affiliated with, endorsed by or sponsored by Harvey AI Corp. The name does not imply API compatibility, authorization or feature parity. Review generated outputs against source documents and professional judgment.
