# AGENTS.md

Guidance for AI coding agents working in this repository. Humans: see
[CONTRIBUTING.md](CONTRIBUTING.md).

## What this repo is

The `mailingkit` Python package: a provider-agnostic transactional email library. **The
package is the product.** Examples, docs and the website exist to demonstrate it and must
never shape its API.

```
src/mailingkit/            the package
  client.py                MailingKit and SyncMailingKit (public entry points)
  message.py               EmailMessage, Address, Attachment
  validation.py            safety checks and Limits
  templates.py             Template, TemplateRenderer
  providers/               EmailProvider contract, built-in adapters, registry
  contrib/                 optional framework glue (never imported by the core)
tests/                     pytest suite, fixtures in tests/fixtures
examples/                  standalone apps using the package; not shipped
```

## Rules

1. The core depends only on Jinja2. Anything else is an optional extra, imported lazily.
2. Never import a web framework outside `mailingkit.contrib`.
3. Never put recipients, subjects, bodies, template data or credentials into logs, events or
   exception messages. Credentials use `mailingkit.config.Secret`.
4. Providers receive a validated `EmailMessage` and must translate every failure into a
   `ProviderError` subclass with an honest `retryable` flag.
5. Everything exported from `mailingkit/__init__.py` is public API. Do not rename or remove
   it without a changelog entry.
6. Tests must not need network access or real credentials.
7. Do not use the em dash character anywhere (code, comments, docs, commits).

## Before you finish

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

All four must pass. Commit with Conventional Commits, one logical change per commit, with no
AI attribution trailers.
