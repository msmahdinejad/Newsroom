# Security Policy

## Supported versions

Security fixes are applied to the current `2.x` release line. Older,
unmaintained snapshots are not supported.

| Version | Supported |
| --- | --- |
| 2.x | Yes |
| < 2.0 | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use the repository's private **Security > Report a vulnerability** workflow
(GitHub Private Vulnerability Reporting). If that feature is unavailable,
contact the repository owner privately through the contact method on their
GitHub profile and request a secure reporting channel. Do not include working
credentials, session files, private source content, or personal data in an
initial message.

Include:

- affected version or commit;
- impact and realistic attack scenario;
- minimal reproduction steps;
- whether private access or a live upstream service is required;
- suggested mitigation, if known.

You should receive an acknowledgement within seven days. The maintainers will
triage severity, coordinate a fix and disclosure date, and credit reporters
who request attribution. Please allow a reasonable remediation window before
public disclosure.

## Security boundaries

- This is a single-operator application, not a hardened public multi-tenant
  service.
- Collected source material is untrusted and must never become executable
  instructions.
- Provider values belong only in ignored `.env.providers.local`.
- X access belongs only in ignored `.env.x.local`.
- Telegram credentials and proxy configuration belong only in ignored `.env`;
  the Telethon session belongs in its Docker volume.
- Safe health, logging, and database metadata must never contain access values.

Operational hardening and threat details are documented in
[docs/security/THREAT_MODEL.md](docs/security/THREAT_MODEL.md).
