# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue for a vulnerability.

Email **mukashifna@gmail.com** with:
- a description of the issue and its impact,
- steps to reproduce (or a proof-of-concept),
- affected component/service and version/commit.

You can expect an acknowledgement within **5 business days** and a status update within
**15 business days**. Coordinated disclosure is appreciated; please give us a reasonable
window to ship a fix before any public write-up.

## Supported versions

The project is pre-1.0. Only the latest `main` receives security fixes until a tagged
release line exists.

| Version | Supported |
|---|---|
| `main` (latest) | ✅ |
| tagged pre-releases | ⚠️ best-effort |

## Security posture (by design)

Provenance is built for **air-gapped / on-premise** deployment:

- **No authentication in v1** — it is a single-user, local-first system and must not be
  exposed to untrusted networks without an auth layer in front of the Gateway.
- **Untrusted document ingestion is an attack surface.** Uploads are validated at the
  Gateway (MIME allowlist, size cap, safe parsing against malformed/zip-bomb PDFs — R67);
  report any bypass.
- **Fully open-source, permissively-licensed stack** with a CI license-audit (R59), so the
  dependency supply chain stays auditable for on-prem legal review.
- **Secrets** belong in `.env` (git-ignored), never in committed files. See `.env.example`
  for the expected variables.
