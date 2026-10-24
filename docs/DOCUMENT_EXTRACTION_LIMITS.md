# Local report extraction budgets

Original uploaded/imported files remain the authority. Extraction is a rebuildable
index; exceeding a budget does not delete or truncate the original file.

`backend/document_parse_budget.py` is the single budget definition:

- 25 MiB source bytes, checked before decoding uploads and while hashing sources.
- At most two parser workers per backend process, immediate busy response beyond
  capacity (no unbounded queue). Each worker is spawned, never the request thread.
- 20-second wall lifetime, killed and reaped before releasing its slot; inability
  to reap retains the slot instead of admitting more workers.
- 768 MiB parser address-space limit on POSIX; Windows process-memory job limit.
  Unsupported or failed isolation refuses extraction, rather than running inline.
- DOCX: 2,048 ZIP entries, 32 MiB declared expanded archive, 8 MiB document XML;
  XML reads are bounded as well as metadata checks.
- PDF: 500 pages, 100,000 extracted characters per page; all formats have a
  1,000,000-character total extraction limit and an 8 MiB serialized result cap.

Budget failures return `ARCHIVED_NOT_SEARCHABLE` with
`DOCUMENT_RESOURCE_LIMIT`; saturation returns `DOCUMENT_PARSER_BUSY`.
No partial text is recorded as `SEARCHABLE`. Rebuilding an existing report and
hitting a limit clears its obsolete index chunks, not its archived source. The
user may retry a busy document after capacity is available. Malformed PDF/DOCX
and OCR-required files retain their existing distinct statuses.

Parser diagnostic stdout/stderr are discarded inside the isolated child because
third-party warnings can contain source bytes. Public APIs and MCP errors use
fixed safe messages rather than provider exception bodies.

The pypdf requirement is >=6.21.2,<7; all three platform locks pin 6.21.2. This
version was the latest official release checked on 2026-10-23:

- https://pypi.org/project/pypdf/6.21.2/
- https://github.com/py-pdf/pypdf/releases
- https://github.com/py-pdf/pypdf/security/advisories/GHSA-gmh7-3g9r-mjh5
- https://github.com/py-pdf/pypdf/security/advisories/GHSA-39mj-jf6j-2qj3
- https://github.com/py-pdf/pypdf/security/advisories/GHSA-f54x-cmq8-qg57

Dependency upgrades and runtime budgets are separate controls: upgrading the
parser does not replace bounded admission, memory, output and lifetime.
