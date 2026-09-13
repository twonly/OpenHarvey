# OpenHarvey

**An open-source AI workspace for contracts and tender documents.**

[中文说明](README.zh-CN.md) · [Website](https://openharvey.com) · [English website](https://openharvey.com/en) · [Try the workspace](https://openharvey.com/demo) · [Deployment](docs/deployment.md)

OpenHarvey connects source documents, conversations and saved deliverables. It is built around the structure of contract work: clauses, attachments, evidence, review playbooks and revisions.

## Why a dedicated workspace?

- **Document-centered work.** Organize the primary agreement, tender documents, attachments and conversations in one contract workspace.
- **Trace findings to sources.** Follow valid citations to highlighted pages or paragraphs. Read original text and outputs side by side.
- **Configurable review.** Bring your own Skills, risk playbooks, party perspective and model settings.
- **Flexible deliverables.** Save summaries, risk reports, clause comparisons and supported custom artifacts, including Markdown, HTML, text, JSON, CSV and SVG. Summary/review/revision workflows also generate Word files. HTML previews run in a restricted iframe.
- **Native agents.** OpenCode handles tools, Skills, sessions and permissions. The application adds document context, navigation, persistence and delivery receipts.
- **Sandbox execution.** Cloud mode runs agents in E2B. Application permissions govern account and document access. Self-hosting the web application does not automatically replace external sandbox or model services.

The website supports Chinese and English. **The application UI, built-in examples and some report fields are primarily Chinese in v0.1.0.** Full English UI and English-contract evaluation are on the roadmap.

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
