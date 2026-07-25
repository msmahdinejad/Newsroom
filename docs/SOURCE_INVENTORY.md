# Source Inventory Schema

The production source workbook is private operational data. It is intentionally
excluded from Git, the Docker context, packages, and release archives. This
document describes its portable interface only.

## Authoritative workbook

The importer reads the `All Sources` worksheet in an `.xlsx` workbook supplied
explicitly with `NEWSROOM_SOURCE_WORKBOOK` or the `--workbook` command option.
The sheet has these columns, in order:

```text
ID, Platform, Type, Name, Handle / ID, Direct URL, Primary Topic, Tags,
Language, Content Mode, Speed 1-5, Informal 1-5, Noise 1-5, Community?,
Open-source/API?, Risk, Verification, Discovery Source, Tier, Coverage Score
```

`ID` is the workbook row identity. The importer derives a stable normalized
source identity from platform, handle, and URL, so display-name edits do not
duplicate a source. A duplicate or unusable row remains represented with an
explicit inactive reason; importing never deletes collected items.

## Public example

[`examples/source_inventory.example.csv`](../examples/source_inventory.example.csv)
contains two synthetic rows with the exact headers. It has no production
source, account, cookie, chat, or credential data. Convert/copy the header and
rows into an `All Sources` sheet when creating a test workbook.

## Import and verification

```powershell
uv run newsroom sources reconcile --workbook .\path\to\source-radar.xlsx
uv run newsroom sources status
```

Repeated reconciliation is idempotent. A source may be active only after a
bounded attempted validation; otherwise it stays inactive with its safe reason.
The scheduled collectors preserve cursors, attempt timestamps, and health
state in PostgreSQL.
