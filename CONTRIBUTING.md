# Contributing to `polygon-news-mcp`

Thanks for taking the time to contribute.  This project is small and
batch-orientated; a tight, focused PR is much easier to review than a
large omnibus.

## Bootstrap

```bash
git clone https://github.com/kevinkda/polygon-news-mcp.git
cd polygon-news-mcp

uv sync --extra dev
uv run pre-commit install
```

Copy `.env.example` to `.env` and set `POLYGON_API_KEY` so the
integration tests can spot-check live Polygon behavior if you opt in.

## Workflow

1. Create a topic branch from `main`:

   ```bash
   git switch -c feature/short-description
   ```

2. Make small, logical commits.  Conventional commit prefixes
   (`feat`, `fix`, `docs`, `test`, `chore`, `refactor`) are required.
3. Run the full local CI gate before pushing:

   ```bash
   bash scripts/local-ci.sh
   ```

   This runs `ruff check`, `ruff format --check`, `mypy --strict`,
   `bandit -r src -lll`, `pip-audit`, `pytest --cov`, and (best-effort)
   `pre-commit run --all-files`.

4. Open a PR using the template in `.github/PULL_REQUEST_TEMPLATE.md`.

## Code style

- Python 3.11+ with full type hints.
- 120-char line limit (handled by ruff format).
- Errors raised by the public surface MUST be subclasses of `PolygonError`.
- Do not log raw response bodies.  The API key never appears in URLs (we
  send it as a Bearer header), so logs cannot accidentally echo it — keep
  it that way: never log raw httpx Response objects.
- New tools must include:
  - A Pydantic input model in `models.py` with anchored regexes.
  - Unit tests for normal / 401 / 404 / 429 / 5xx paths.
  - A README "Tooling surface" entry with the four-section format
    (when to use / input / returns / example).

## Security

- Never commit secrets — pre-commit hooks will block obvious cases via
  `detect-secrets` (always on) and `gitleaks` (manual stage).
- Never disable TLS verification.
- Do not hard-code an API key in source; the key comes from
  `POLYGON_API_KEY`.

## Licensing

By submitting a PR you agree your contribution is licensed under MIT
(matching the repo `LICENSE`).
