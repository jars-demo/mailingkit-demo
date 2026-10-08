# Contributing to MailingKit

Thanks for helping. MailingKit is a library first: every change should keep it small, typed,
framework-independent and safe by default.

## Set up

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```bash
git clone https://github.com/jars-demo/mailingkit-demo.git
cd mailingkit-demo
uv sync
```

## Checks

Run these before opening a pull request. CI runs the same commands.

```bash
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run mypy                   # strict type checking
```

Tests never need real provider credentials. Use `MemoryProvider`, the fake SMTP server in
`tests/test_providers.py`, or `httpx.MockTransport` for HTTP providers.

## Ground rules

- **The core stays light.** `mailingkit` depends only on Jinja2. New integrations (providers
  with SDKs, queues, tracing) go behind an optional extra and are imported lazily.
- **No framework imports in the core.** Framework glue lives in `mailingkit.contrib`.
- **Never log personal data or secrets.** No recipients, subjects, bodies, template data or
  credentials in log lines, events or exception messages.
- **Public API changes need a reason.** Anything exported from `mailingkit/__init__.py` is
  public. Prefer adding over changing, and note it in `CHANGELOG.md`.

## Adding a provider

1. Create `src/mailingkit/providers/<name>.py` with a subclass of `EmailProvider`.
2. Map every failure to a `ProviderError` subclass with an honest `retryable` value.
3. Implement `from_env()` reading `MAILINGKIT_<NAME>_*` variables; wrap credentials in
   `Secret`.
4. Register it in `_BUILTIN` in `providers/__init__.py`. If it needs a third-party package, add
   an extra in `pyproject.toml` and import that package inside the provider, not at module
   level.
5. Test the payload, the success path and each error mapping with a fake transport.
6. Document it in the README provider table and configuration reference.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
`test:`, `refactor:`, `build:`, `ci:`, `chore:`. One logical change per commit, with the reason
in the body.
