# Deployment

## Local development

Follow the README to create an isolated Python environment, provision an administrator and start the web server. Use a stable data directory outside this checkout for anything you want to keep.

For explicit local OpenCode setup, copy `deploy/provider.example.json` to a private file outside the repository and fill the provider URL/model ID. Use its environment-variable API key placeholder. Start the runtime in a separate terminal with the same `CW_DATA_DIR`:

```sh
export CW_SANDBOX_BACKEND=local
.venv/bin/python -m contract_web.cli local-runtime admin \
  --port 4096 --web-url http://127.0.0.1:8080 \
  --provider-config /absolute/private/provider.json
```

Provide `CW_MODEL_API_KEY` through your secret manager or shell environment. Never put real credentials into repository files. Model configuration is also available in the UI. Test the chosen provider before uploading sensitive documents.

## E2B cloud mode

1. Install the Python requirements and authenticate with your own E2B account.
2. Build the pinned OpenCode 1.16.2 template with `python deploy/e2b/build_template.py`. This creates paid/usage-metered external resources according to your E2B account.
3. Build the Web image using `deploy/Dockerfile.web`.
4. Mount persistent storage at `/data` and set the variables below.
5. Create an administrator in the running container using the CLI; keep the generated password private. Configure model access and verify a fictional document task.

| Variable | Purpose |
| --- | --- |
| `CW_DATA_DIR=/data` | Persistent database, originals, outputs, secrets and checkpoints |
| `CW_SANDBOX_BACKEND=e2b` | Cloud sandbox execution |
| `E2B_API_KEY` | Your E2B credential, private runtime variable |
| `E2B_TEMPLATE` | Your built template name or ID |
| `CW_PUBLIC_ORIGIN` | Exact public HTTPS origin |
| `CW_ADDITIONAL_ORIGINS` | Optional explicit additional origins, comma separated |
| `CW_SECURE_COOKIE=1` | Secure production cookies |

Optional email/OAuth registration uses your own `CW_SUPABASE_URL` and `CW_SUPABASE_PUBLISHABLE_KEY`. Configure permitted callback URLs as `https://your-domain/auth/callback` in that project. Use the publishable/anon key, never a service-role key in public configuration.

Optional platform trial inference uses private `CW_TRIAL_MODEL_KEY`, `CW_TRIAL_MODEL_BASE_URL` and `CW_TRIAL_MODEL`. Personal model configuration is independent. E2B and inference usage are not included with the open-source license.

## Railway

Create a service from this repository, build with `deploy/Dockerfile.web`, use the start command in `railway.json`, attach a persistent volume at `/data`, set `/health` as the health check and keep one replica / one worker. The application owns background queues and event collection, so disable automatic sleeping. Verify the platform's effective configuration after deployment.

The current implementation uses SQLite and files, not distributed shared storage. Do not scale horizontally without adapting persistence and background coordination.

## Acceptance and backups

Verify HTTPS, login, an uploaded fictional document, a real model answer with a valid source citation, streaming, an actual saved artifact and download. Restart the service and check persistence. A `/health` 200 only confirms the web service.

For a consistent backup, stop application writes and copy the complete data directory, including the database, files and encryption master key. Keep backups private and test restoration. Restoring an old backup discards subsequent writes; reconcile them before restoring production.

## Public website

`PYTHONPATH=. python scripts/export_website.py /absolute/new/output-directory --workbench-origin https://your-backend.example.com` generates a static Chinese homepage, `/en`, bilingual information pages, sitemap and crawler files. It does not include business data. Product links stay on the website domain; Vercel rewrites forward workbench pages, assets, authentication and API requests to the HTTPS backend. Private responses are not cached, and artifact previews retain the backend CSP. Keep the backend's `CW_PUBLIC_ORIGIN`, explicit `CW_ADDITIONAL_ORIGINS`, and your authentication provider's callback allowlist aligned with the website domain. Cookies are host-only, so existing users must sign in again on a new domain; account data stays in the same backend.
