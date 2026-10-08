# Examples

Small, runnable applications that use MailingKit. They are not part of the package; each one
shows how an application plugs MailingKit in.

All of them print emails to the terminal by default. To send for real, set
`MAILINGKIT_PROVIDER` and the provider's variables (see the main README).

| Example                 | Shows                                                                 | Run from the repository root                                                   |
| ----------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [`basic/`](basic/)      | one client sending SaaS, recruitment and e-commerce emails with typed templates and an idempotency key | `uv run python examples/basic/send.py`                         |
| [`fastapi/`](fastapi/)  | signup and password reset endpoints, error handling, client lifecycle | `uv run --with fastapi --with uvicorn --with "pydantic[email]" uvicorn app:app --app-dir examples/fastapi` |
| [`django/`](django/)    | Django's own `send_mail()` routed through MailingKit with no code changes | `uv run python examples/django/app.py`                                     |

Try the file provider to open the results in your mail client:

```bash
MAILINGKIT_PROVIDER=file uv run python examples/basic/send.py
# then open .mailingkit/outbox/*.eml
```
