# Feishu / Lark connector

## Connect an account

Open **Connectors**, choose Feishu or Lark, and follow the official app-creation and account-authorization pages. Existing connections reuse their app. Each workbench account has its own connection; demo accounts cannot connect. Application permissions and administrator approval may be required by the organization. Additional permissions require reconnecting and approving the new scopes.

The connector requests document search/read/write, wiki read and Base app/table/field/record scopes. User messaging additionally requires `im:message.send_as_user` and `im:message`; contact search requires `contact:user:search`. The user must explicitly request sending a message. Permissions do not imply that an operation has been performed or verified.

Feishu document and Base read/write were exercised with a real account and fictional contracts. Lark international authorization and business operations, and actual message sending, still require live-account acceptance. The two platforms use separate account and app systems. An existing connection retains its original platform.

## Deploy with E2B

Use `deploy/Dockerfile.web`, a persistent volume at `/data`, one web worker and one replica. The image installs official CLI **1.0.76** and builds a private credential adapter against the same upstream version. Set:

```text
CW_FEISHU_ENABLED=1
CW_FEISHU_TRANSPORT=direct_cli
CW_PUBLIC_ORIGIN=https://your-workspace.example
CW_SANDBOX_BACKEND=e2b
CW_SECURE_COOKIE=1
```

Configure the existing E2B and model settings separately. Never enable `CW_LOCAL_DEV_USER` on a public deployment. When the website is hosted separately, forward `/connectors` and the existing authenticated API routes to the control plane. The website exporter includes these rewrites.

The standard E2B template must provide OpenCode **1.16.2**, Node/npm and outbound HTTPS. At the first authorized task, existing owned sandboxes install CLI 1.0.76 if missing and receive the runtime launcher. Subsequent calls reuse it. A prebuilt template can avoid the first-use installation cost; no user credentials belong in a template. Embedded CLI Skills and `--help` provide native tool discovery without a business-operation MCP proxy.

## Credentials and execution

- Linux CLI credentials are encrypted by the official CLI under `/data/connectors/<user-id>`; its per-account encryption key must be backed up with the credentials. This protects stored values, not against an administrator with access to the volume.
- The adapter uses the official credential store and refresh implementation. App secrets and refresh tokens stay on the control plane; only the current user's access token, identity, scopes and expiry are injected via E2B SDK.
- User/workspace ownership, deployment metadata, sandbox binding/generation and connection revision are checked before injection. Each contract space owns a sandbox; conversations within it do not have separate operating-system boundaries.
- The launcher reads the current token for every CLI command. Feishu / Lark business requests leave directly from E2B. Agents do not need a public tunnel back to the control plane.
- Refresh is shared per account and unchanged credentials are not repeatedly injected. Expired credentials fail explicitly. Disconnect stops renewal and clears accessible runtime credentials; already issued tokens and in-flight writes cannot be revoked instantly.
- The application archive excludes runtime credential paths. E2B pause snapshots may retain them; resume rechecks credentials before tasks execute. Shell-capable agents can access the runtime token within their own sandbox.

## Delivery and failure handling

Read policy sources before applying them to a contract. Keep source links distinct from contract citations. Read Base field definitions before writes, return real object IDs and links, and disclose partial failures. After an uncertain write, reconcile using the returned ID or a run identifier before attempting creation again. A CLI process exit alone does not prove a report is complete.

Upstream: [official CLI](https://github.com/larksuite/cli/tree/v1.0.76), [credential refresh](https://github.com/larksuite/cli/blob/v1.0.76/internal/auth/uat_client.go).
