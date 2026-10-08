"""Send three emails from three different kinds of application with one MailingKit client.

Run from the repository root:

    uv run python examples/basic/send.py

With no MAILINGKIT_PROVIDER set, the emails are printed instead of sent. Set
MAILINGKIT_PROVIDER=file to get .eml files you can open in a mail client.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from mailingkit import MailingKit, Template

TEMPLATES = Path(__file__).parent / "templates"


# Each application owns its template data. MailingKit only checks it against the model.


@dataclass
class Welcome:  # a SaaS product
    name: str
    product: str
    login_url: str


@dataclass
class CandidateSelected:  # a recruitment system
    candidate_name: str
    company_name: str
    next_round: str
    interview_url: str


@dataclass
class OrderShipped:  # an online store
    customer_name: str
    order_number: str
    tracking_url: str


WELCOME = Template("welcome", Welcome)
CANDIDATE_SELECTED = Template("candidate-selected", CandidateSelected)
ORDER_SHIPPED = Template("order-shipped", OrderShipped)


async def main() -> None:
    mail = MailingKit.from_env(
        templates=TEMPLATES, default_sender="Example Platform <no-reply@example.com>"
    )
    async with mail:
        await mail.send_template(
            WELCOME,
            Welcome(name="Ada", product="Acme Cloud", login_url="https://app.example.com"),
            to="Ada Lovelace <ada@example.com>",
        )
        await mail.send_template(
            CANDIDATE_SELECTED,
            CandidateSelected(
                candidate_name="Grace",
                company_name="Acme",
                next_round="technical interview",
                interview_url="https://jobs.example.com/interview/123",
            ),
            to="grace@example.com",
        )
        result = await mail.send_template(
            ORDER_SHIPPED,
            OrderShipped(
                customer_name="Alan",
                order_number="1001",
                tracking_url="https://shop.example.com/track/1001",
            ),
            to="alan@example.com",
            # The same key never sends twice, even if this line runs again after a crash.
            idempotency_key="order-shipped:1001",
        )
        print(f"Last send accepted: id={result.id} provider={result.provider}")


if __name__ == "__main__":
    asyncio.run(main())
