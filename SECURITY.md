# Security

This is an early release, not an independently audited legal or security product. Only the latest published release is maintained.

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/twonly/OpenHarvey/security/advisories/new). If that channel is unavailable, contact the repository owner without posting exploit details, credentials or private documents publicly.

## Deployment boundaries

- Bind local development to loopback. Local processes do not isolate multiple users at the operating-system level.
- Use HTTPS and secure cookies in production. Keep the data directory, master key, private model configuration and backups outside the source tree.
- Cloud agents receive permitted materials in E2B and send relevant context to the chosen model provider. Review all provider terms and data locations.
- Conversations in the same contract workspace may share a sandbox. Document scopes are enforced by application permissions and runtime tool policies, not separate per-conversation VMs.
- Platform inference keys remain server-side; personal model configuration may require credentials inside its runtime.
- Saved outputs and checkpoints remain on application storage independently of sandbox destruction. Define your own retention and backup policy.
- Keep one web replica and one worker for the current SQLite/file-backed deployment. Do not use ephemeral functions as a replacement for the persistent worker.
- Test restoration of the database, files and matching master key together before relying on backups.

HTML deliverables are untrusted content and are previewed in a restricted iframe. Preserve its sandbox, content security policy and message validation.

Do not claim that sandboxing guarantees offline processing, zero data transfer, legal accuracy or compliance certification.
