# MailingKit

**Transactional email for Python, without the plumbing.**

MailingKit is a small, typed library you drop into any Python application that needs to send
email. Your code talks to one clean API. MailingKit renders the template, validates the message,
picks the provider, retries transient failures and gives you one consistent result and one set
of errors, whichever provider sits underneath.

```python
from mailingkit import MailingKit

mail = MailingKit.from_env()

await mail.send_template("welcome", {"name": "Ada"}, to="ada@example.com")
```

- **Provider-agnostic.** SMTP, Resend, a console printer for development, or your own adapter.
  Switching provider is an environment variable, not a code change.
- **Framework-independent.** Plain Python, FastAPI, Django, Celery, scripts, workers. The core
  depends only on Jinja2.
- **Safe by default.** Prints instead of sending until you configure a provider. Blocks header
  injection, escapes HTML, never logs recipients or secrets.
- **Typed.** Bind templates to dataclasses or Pydantic models and catch missing data before an
  email goes out. Ships `py.typed`, checked with `mypy --strict`.

**Documentation, workshop and API reference:** [mailingkit.jishanahmed.in](https://mailingkit.jishanahmed.in)

> Status: `0.1.0`, alpha. The API is small on purpose and may still change before `1.0`.

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Templates](#templates)
- [Providers](#providers)
- [Development mode](#development-mode)
- [Errors, retries and idempotency](#errors-retries-and-idempotency)
- [Framework integration](#framework-integration)
- [Testing your application](#testing-your-application)
- [Configuration reference](#configuration-reference)
- [Security](#security)
- [Roadmap](#roadmap)

## Install

```bash
pip install mailingkit             # core: console, file, memory and SMTP providers
pip install "mailingkit[resend]"   # adds the Resend provider (httpx)
```

Python 3.11 or newer, on Linux, macOS and Windows.

## Quick start

**1. Configure** with environment variables (or pass the same values to `MailingKit(...)`):

```bash
MAILINGKIT_PROVIDER=smtp
MAILINGKIT_FROM_EMAIL=no-reply@example.com
MAILINGKIT_FROM_NAME="Example App"
MAILINGKIT_SMTP_HOST=smtp.example.com
MAILINGKIT_SMTP_USERNAME=apikey
MAILINGKIT_SMTP_PASSWORD=...
```

Leave `MAILINGKIT_PROVIDER` unset during development and every email is printed to the
terminal instead of sent.

**2. Create one client** when your application starts:

```python
from mailingkit import MailingKit

mail = MailingKit.from_env()
```

**3. Send:**

```python
result = await mail.send(
    to="ada@example.com",
    subject="Your export is ready",
    html="<p>Hi Ada, <a href='https://example.com/exports/42'>download it here</a>.</p>",
)
print(result.id, result.provider_message_id)
```

A plain text part is generated from the HTML automatically. Not in async code? Use the
blocking client, which has the same methods:

```python
from mailingkit import SyncMailingKit

mail = SyncMailingKit.from_env()
mail.send(to="ada@example.com", subject="Hi", text="Hello Ada")
```

## Templates

Templates live in a folder, one subfolder per email:

```
templates/
    _layouts/base.html        shared layout ({% extends "_layouts/base.html" %})
    welcome/
        subject.txt           required
        body.html             autoescaped HTML
        body.txt              optional, generated from body.html when missing
```

```python
mail = MailingKit.from_env(templates="templates")   # or MAILINGKIT_TEMPLATES_DIR

await mail.send_template("welcome", {"name": "Ada"}, to="ada@example.com")
```

Rendering uses a sandboxed Jinja2 environment with HTML escaping on and undefined variables
treated as errors, so a missing value raises `TemplateDataError` instead of sending
"Hello ,".

### Typed template data

Bind a template to a dataclass or a Pydantic model and the data is checked before rendering:

```python
from dataclasses import dataclass
from mailingkit import Template

@dataclass
class CandidateSelected:
    candidate_name: str
    company_name: str
    next_round: str
    interview_url: str

CANDIDATE_SELECTED = Template("candidate-selected", CandidateSelected)

await mail.send_template(
    CANDIDATE_SELECTED,
    CandidateSelected(
        candidate_name="Ada",
        company_name="Acme",
        next_round="Technical interview",
        interview_url="https://acme.example/interview/123",
    ),
    to="ada@example.com",
)
```

A plain dict works too and is validated against the model. Every missing and unknown field is
reported at once:

```
TemplateDataError: Template 'candidate-selected' data is invalid:
missing required fields: interview_url, next_round
```

Preview a template without sending it with `mail.render(template, data)`.

## Providers

| Name      | Sends real email | Install                 | Use it for                                   |
| --------- | ---------------- | ----------------------- | -------------------------------------------- |
| `console` | no               | core                    | local development (the default)              |
| `file`    | no               | core                    | previewing `.eml` files in a mail client     |
| `memory`  | no               | core                    | automated tests                              |
| `smtp`    | yes              | core                    | any SMTP service, Mailpit, Amazon SES SMTP   |
| `resend`  | yes              | `mailingkit[resend]`    | the Resend HTTP API                          |

Pick one with `MAILINGKIT_PROVIDER`, or pass an instance:

```python
from mailingkit import MailingKit
from mailingkit.providers import SmtpProvider

mail = MailingKit(
    SmtpProvider("smtp.example.com", username="apikey", password="..."),
    default_sender="no-reply@example.com",
)
```

### Writing your own provider

A provider is one async method. Map failures to MailingKit errors and say whether a retry
could help:

```python
from mailingkit import EmailProvider, ProviderResponse, RateLimitError, TemporaryProviderError

class AcmeMailProvider(EmailProvider):
    name = "acme"

    async def send(self, message, *, idempotency_key=None):
        response = await acme_client.post_email(...)  # message is rendered and validated
        if response.status == 429:
            raise RateLimitError("Acme is throttling", retry_after=response.retry_after)
        if response.status >= 500:
            raise TemporaryProviderError(f"Acme returned {response.status}")
        return ProviderResponse(provider_message_id=response.id)

mail = MailingKit(AcmeMailProvider(), default_sender="no-reply@example.com")
```

To make it selectable with `MAILINGKIT_PROVIDER=acme`, implement `from_env()` and publish an
entry point from your package:

```toml
[project.entry-points."mailingkit.providers"]
acme = "acme_mailingkit:AcmeMailProvider"
```

## Development mode

Accidentally emailing real customers from a laptop is the classic mistake. MailingKit makes
it hard:

- **No provider configured means `console`.** Messages are printed, nothing leaves the machine.
- **`MAILINGKIT_PROVIDER=file`** writes each email to `.mailingkit/outbox/*.eml`. Double-click
  one to see exactly what the recipient would see.
- **`MAILINGKIT_REDIRECT_TO=qa@example.com`** sends everything, from any code path, to one
  inbox. Staging uses real delivery without reaching real users. The original recipients are
  kept in an `X-MailingKit-Original-To` header.

## Errors, retries and idempotency

Every provider failure is translated into the same exceptions, so switching providers never
changes your error handling:

```
MailingKitError
├── ConfigurationError
├── ValidationError                 bad address, header injection, too large...
├── TemplateError                   not found, invalid data, render failure
└── ProviderError                   .retryable  .provider  .status_code
    ├── AuthenticationError
    ├── RateLimitError              .retry_after
    ├── RecipientRejectedError
    ├── TemporaryProviderError
    └── PermanentProviderError
```

**Retries.** Errors marked `retryable` are retried inside the call with exponential backoff and
jitter (3 attempts by default, `Retry-After` honoured). Tune or disable with
`MailingKit(retry=RetryPolicy(max_attempts=5))` or `retry=NO_RETRY`.

**Idempotency.** Pass a key that identifies the business event, and the same key never sends
twice:

```python
await mail.send_template(
    "order-shipped", data, to=customer.email, idempotency_key=f"order-shipped:{order.id}"
)
```

A repeat returns the first `SendResult` with `duplicate=True`. Providers that support it
(Resend) receive the key too. The default store is in process memory; pass your own
`IdempotencyStore` to share keys across processes.

**Hooks.** Observe sends for metrics or tracing:

```python
def on_event(event):          # sync or async
    metrics.increment(event.name, tags={"provider": event.provider})

mail = MailingKit.from_env(hooks=[on_event])
```

Events are `mail.sent`, `mail.failed`, `mail.retry` and `mail.duplicate`. They carry ids,
provider and template name, never recipients or content. A failing hook is logged and never
breaks sending.

## Framework integration

MailingKit does not depend on any web framework. Create one client at startup and use it.

**FastAPI**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from mailingkit import MailingKit

mail = MailingKit.from_env()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await mail.aclose()

app = FastAPI(lifespan=lifespan)

@app.post("/signup")
async def signup(email: str):
    await mail.send_template("welcome", {"email": email}, to=email)
    return {"ok": True}
```

**Django.** Route all of Django's email through MailingKit, including `send_mail()`, password
resets and admin error emails, without changing application code:

```python
# settings.py, Django 6.1 and newer
MAILERS = {"default": {"BACKEND": "mailingkit.contrib.django.EmailBackend"}}

# older Django
EMAIL_BACKEND = "mailingkit.contrib.django.EmailBackend"
```

**Celery, RQ, scripts.** Use `SyncMailingKit`. It is safe to call from any thread.

See [`examples/`](examples/) for complete, runnable apps.

## Testing your application

Use the in-memory provider. No network, no credentials:

```python
from mailingkit import MailingKit
from mailingkit.providers import MemoryProvider

async def test_signup_sends_welcome_email():
    provider = MemoryProvider()
    mail = MailingKit(provider, default_sender="app@example.com", templates="templates")

    await signup(mail, "ada@example.com")

    assert provider.last.subject == "Welcome to Acme"
    assert provider.sent_to("ada@example.com")
```

`provider.fail_next(TemporaryProviderError("boom"))` scripts failures to test your retry and
error paths.

## Configuration reference

| Variable                        | Meaning                                             | Default               |
| ------------------------------- | --------------------------------------------------- | --------------------- |
| `MAILINGKIT_PROVIDER`           | `console`, `file`, `memory`, `smtp`, `resend`, plugin | `console`           |
| `MAILINGKIT_FROM_EMAIL`         | default sender address                              |                       |
| `MAILINGKIT_FROM_NAME`          | default sender display name                         |                       |
| `MAILINGKIT_TEMPLATES_DIR`      | template folder                                     |                       |
| `MAILINGKIT_REDIRECT_TO`        | send every email here instead                       |                       |
| `MAILINGKIT_MAX_ATTEMPTS`       | attempts per send for transient failures            | `3`                   |
| `MAILINGKIT_SMTP_HOST`          | SMTP server (required for `smtp`)                   |                       |
| `MAILINGKIT_SMTP_PORT`          | SMTP port                                           | `587` / `465` / `25`  |
| `MAILINGKIT_SMTP_SECURITY`      | `starttls`, `ssl` or `none`                         | `starttls`            |
| `MAILINGKIT_SMTP_USERNAME`      | SMTP username                                       |                       |
| `MAILINGKIT_SMTP_PASSWORD`      | SMTP password                                       |                       |
| `MAILINGKIT_SMTP_TIMEOUT`       | seconds                                             | `30`                  |
| `MAILINGKIT_RESEND_API_KEY`     | Resend API key (required for `resend`)              |                       |
| `MAILINGKIT_FILE_DIR`           | output folder for `file`                            | `.mailingkit/outbox`  |
| `MAILINGKIT_CONSOLE_SHOW_HTML`  | also print the HTML body                            | `false`               |

The `MAILINGKIT_` prefix keeps these from colliding with other libraries' `MAIL_*` settings.

## Security

- **Header injection:** line breaks are rejected in subjects, display names, addresses and
  custom headers. Reserved headers (`From`, `To`, `Bcc`...) cannot be overridden.
- **HTML:** template data is escaped in HTML bodies. Templates render in a Jinja2 sandbox and
  are only loaded from your template folder, never from user input.
- **Secrets:** credentials are held in a `Secret` type that never appears in a repr, log line
  or error message.
- **Logs and hooks** contain ids, provider and template names only. Recipients, subjects and
  template data stay out by default.
- **TLS:** SMTP uses STARTTLS with certificate verification by default and refuses to send
  credentials over a plain connection.
- **Limits:** recipient count and message size are capped (`Limits`), and attachment filenames
  are checked for path tricks.

## Roadmap

MailingKit grows in small steps. The library stays the product.

- **0.1** (this release): core client, templates, console, file, memory, SMTP and Resend
  providers, retries, idempotency, hooks, Django backend.
- **0.2**: `mail.enqueue()` plus an optional `mailingkit worker` for background sending
  (Redis first), a shared idempotency store, more providers (Amazon SES, Postmark).
- **0.3**: normalized delivery events from provider webhooks, a local preview inbox,
  OpenTelemetry hooks.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and pull requests are welcome.

## License

[MIT](LICENSE) © Jishanahmed AR Shaikh (JARS)
