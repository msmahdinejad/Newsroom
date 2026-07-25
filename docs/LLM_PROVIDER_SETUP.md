# LLM Provider Setup

## Canonical local configuration

Editorial provider access is loaded only from the ignored file
`.env.providers.local`. Copy the safe template and edit the local copy:

```powershell
Copy-Item .env.providers.example .env.providers.local
```

On Linux:

```bash
cp .env.providers.example .env.providers.local
```

Do not add provider access to `.env`, Compose YAML, tracked fixtures, or command
arguments. Never commit the local file.

The four access pools are comma-separated:

```dotenv
GEMINI_API_KEYS=
MISTRAL_API_KEYS=
GROQ_API_KEYS=
NVIDIA_API_KEYS=
# Optional shared egress proxy; leave blank for direct provider access.
LLM_PROXY_URL=
```

Model lists must use exact provider model IDs. A configured name is only a
candidate; it is not enabled until the live validation suite passes.

## Validation

Run a bounded validation from the application environment:

```powershell
uv run python -m newsroom.editorial.router validate
```

The command tests each non-empty access value without printing it. It records
only provider/model identifiers, one-way access fingerprints, safe status,
latency, timestamps, failure categories, and supported capabilities.

A production route must pass:

1. endpoint connectivity and authentication;
2. minimal Persian generation;
3. the required structured schema;
4. response parsing compatible with grounding checks;
5. bounded input/output behavior;
6. end-to-end router integration.

Missing access is `not configured`. Authentication rejection is not assigned
until endpoint, header format, model availability, parameters, proxy behavior,
timeout, provider availability, quota, and account state have been checked.

## Routing and quotas

Default provider order:

```text
Gemini -> Mistral -> Groq -> NVIDIA -> deterministic fallback
```

Within a provider:

```text
preferred validated model/key
-> another healthy key
-> another validated model
-> provider cooldown
```

Gemini defaults are queue size 32, concurrency 1, five-second minimum request
spacing, effective RPM 12, effective TPM 200000, and effective RPD 450.
Gemini quota is treated as project-scoped; adding keys improves resilience but
does not multiply capacity unless separate quota scopes are demonstrated.

The router performs bounded retries and honors retry delays. Invalid access is
isolated, invalid model routes are disabled, and malformed structured output
gets at most one repair attempt through a compatible validated route. Three
consecutive provider-level failures open the provider circuit; one half-open
probe determines recovery.

Provider and queue limits can be changed through the safe variables documented
in `.env.providers.example`; code changes are not required.

## Production activation and rotation

After validation:

```powershell
docker compose up -d --build --force-recreate report-worker scheduler
.\scripts\health.ps1
```

To rotate an access value:

1. edit only `.env.providers.local`;
2. rerun bounded validation;
3. recreate `report-worker` and `scheduler`;
4. verify the safe route/model health state;
5. run the release exposure audit.

```powershell
uv run python scripts\audit_release_exposure.py
```

Never paste an access value into an issue, log excerpt, report, database query,
or health response. Operational support should refer only to provider, safe
key label/fingerprint, model, timestamp, and failure category.

`LLM_PROXY_URL` is also protected local configuration. Its value stays in the
same canonical file and is represented only by a safe transport label in
attempt metadata.

If `LLM_PROXY_URL` intentionally targets local loopback, set
`LLM_PROXY_CONTAINER_HOST=host.docker.internal` in the same local file. The
rewrite happens only inside a container, preserves hidden credentials, and
never changes host-side validation.
