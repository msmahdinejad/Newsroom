# Third-Party Notices

Newsroom is distributed under the MIT License. The project depends
on third-party software that remains under its own license. This notice is
informational and does not replace the license text distributed by each
upstream project.

## Direct runtime dependencies

| Component | Declared license | Project |
| --- | --- | --- |
| SQLAlchemy | MIT | <https://www.sqlalchemy.org/> |
| Alembic | MIT | <https://alembic.sqlalchemy.org/> |
| psycopg | LGPL-3.0-only | <https://www.psycopg.org/> |
| HTTPX | BSD-3-Clause | <https://www.python-httpx.org/> |
| feedparser | BSD-2-Clause | <https://github.com/kurtmckee/feedparser> |
| Pydantic | MIT | <https://github.com/pydantic/pydantic> |
| pydantic-settings | MIT | <https://github.com/pydantic/pydantic-settings> |
| python-dotenv | BSD-3-Clause | <https://github.com/theskumar/python-dotenv> |
| APScheduler | MIT | <https://apscheduler.readthedocs.io/> |
| openpyxl | MIT | <https://openpyxl.readthedocs.io/> |
| Telethon | MIT | <https://github.com/LonamiWebs/Telethon> |
| PySocks | BSD | <https://github.com/Anorov/PySocks> |
| socksio | MIT | <https://github.com/sethmlarson/socksio> |

## Optional external-source tools

| Component | Pinned version/revision | Declared license | Project |
| --- | --- | --- | --- |
| Agent-Reach | `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (`1.5.0`) | MIT | <https://github.com/Panniantong/Agent-Reach> |
| twitter-cli | `0.8.5` | Apache-2.0 | <https://github.com/jackwener/twitter-cli> |

Agent-Reach and twitter-cli are optional upstream tools. They are not authored
by or relicensed by this project. The immutable Agent-Reach revision is used
to keep the audited integration reproducible.

## Development dependencies and transitive packages

Ruff, MyPy, pytest, pytest-asyncio, pytest-cov, and pytest-httpx are direct
development dependencies. The complete resolved dependency graph and exact
versions are recorded in `uv.lock`. Distributors should generate a
license/SBOM report from that lock file for the target platform and retain all
upstream notices required by those licenses.

## Third-party services and content

This repository's license does not cover:

- articles, posts, comments, media, metadata, or other collected content;
- the owner's private source workbook;
- model/provider output;
- Telegram, X, GitHub, YouTube, Reddit, or other platform data;
- trademarks, service names, or APIs operated by third parties.

Operators and redistributors are responsible for upstream terms, copyright,
database rights, privacy requirements, rate limits, and applicable law.
