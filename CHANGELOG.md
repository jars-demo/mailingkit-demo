# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-08

### Added

- `MailingKit` async client with `send()`, `send_template()`, `send_message()`, `render()` and
  `validate()`, plus `SyncMailingKit` for blocking code.
- Immutable `EmailMessage` model with address parsing, header injection protection, recipient
  and size limits.
- File-based Jinja2 templates in a sandbox with autoescaping, strict undefined variables,
  typed data (dataclasses or Pydantic) and automatic plain text bodies.
- Providers: `console` (default), `file`, `memory`, `smtp` and `resend` (optional extra), with
  a provider registry and the `mailingkit.providers` entry point group for plugins.
- Normalized error hierarchy with `retryable`, in-call retries with backoff and `Retry-After`
  support, and idempotency keys with an in-memory store.
- `redirect_to` for staging, event hooks, and logs without personal data.
- Configuration from `MAILINGKIT_*` environment variables, with a `Secret` type for
  credentials.
- Django email backend supporting `MAILERS` (Django 6.1+) and `EMAIL_BACKEND`.

[Unreleased]: https://github.com/jars-demo/mailingkit-demo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jars-demo/mailingkit-demo/releases/tag/v0.1.0
