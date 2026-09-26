# Contract materials user manual

[中文](materials-labs.zh-CN.md) · [Online guide](https://openharvey.com/guide?lang=en#materials) · [Project home](../README.md)

Contract materials groups the main agreement, quotations and supporting files within one contract workspace. Conversations in that workspace can use the available files as needed. It is a **personal Labs option, off by default**.

This manual describes source versions that include Contract materials. Hosted and self-hosted services can run different versions: check whether the option appears under Settings → Labs. Publishing this manual does not mean every service has been upgraded.

## Enable and start

1. Open **Settings → Labs** and enable **Contract materials**. Wait for running or dispatching tasks to finish first.
2. Open a contract workspace and a writable conversation. The main agreement keeps its identity; existing attachments become available across that workspace’s conversations.
3. Open the materials manager from the document panel or the materials count above the composer. Choose **Add materials**, select multiple files, or drag them into the manager.
4. Supported formats are DOCX, text-based PDF, Markdown and TXT. Registered accounts allow up to 20 MB per file; demo limits follow the workspace display.
5. Files are processed sequentially. Each file reports ready, already present or failed. Retry a failed file independently; successful uploads stay saved. Wait for uploads to finish before sending a task.
6. Ask a specific question, for example: “Compare the agreement and quotation on total price, acceptance and payment deadlines. Cite each source and list discrepancies.”
7. Follow citations to the original text. Expand **Cited sources** to see which files the answer cites. Explicitly request a saved file when needed, then preview or download it from deliverables.

## Find, remove and restore

Search filenames, filter by format and open a file by its name. The main agreement is identified separately and cannot be removed from the materials manager.

Removing another file excludes it from future task input. The saved original and historical citations remain available. Use the immediate undo action, or switch the scope filter to removed files and restore it later. Removal does not erase past conversation content.

Uploading content already in the active workspace reuses the existing file. Matching filenames with different contents remain separate documents; no automatic version replacement occurs. State which version to use in the task and remove outdated files when appropriate.

## Tell the assistant which sources to use

All active materials are available for on-demand reading; no per-message checkboxes are required. **Available does not mean read. Cited sources are not proof of full review coverage.**

| Task | Example instruction |
| --- | --- |
| Main agreement only | “Use only the main agreement, ignore the quotation, and cite the payment deadline after acceptance.” |
| Cross-document comparison | “Compare delivery scope in the agreement and technical annex. Identify each file’s terms and discrepancies.” |
| Reference-only document | “Treat the agreement as authoritative. Use this quotation only to compare prices.” |
| Saved output | “Save the differences as a table file, keeping filenames and source citations.” |

Contract materials hold project sources; personal memory holds working preferences; Skills define methods; playbooks define review standards. Contract amounts, parties and deadlines remain grounded in the current source documents.

## Disable and keep your work

Turning the option off restores the existing attachment interface and retains saved materials and historical citations. Re-enabling restores access to the manager. Material scope returns to the existing runtime behavior: local conversations use their main agreement and own attachments, while cloud workspaces keep their existing workspace-wide scope. Disabling does not delete files or retract context already sent to a model.

## Limits and troubleshooting

- Material changes are blocked while workspace tasks run or dispatch. Restore archived or deleted conversations before editing materials.
- This feature uses the existing document parser and does not add OCR for scanned PDFs.
- Refreshing loses browser-held pending upload selections; select failed files again. Successful uploads remain saved.
- Management is per contract workspace. There is no global cross-workspace Vault, folder hierarchy, automatic classification or Review Tables.
- Account isolation remains in place; enabling Labs does not share documents with other accounts.
