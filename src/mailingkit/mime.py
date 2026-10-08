"""Turn an :class:`EmailMessage` into a standard MIME message.

Used by the SMTP and file providers, and available to custom providers that speak raw MIME.
"""

from __future__ import annotations

from email import policy
from email.headerregistry import Address as HeaderAddress
from email.message import EmailMessage as MIMEMessage
from email.utils import formatdate, make_msgid

from mailingkit.message import Address, EmailMessage

__all__ = ["to_mime"]


def _header_address(address: Address) -> HeaderAddress:
    return HeaderAddress(display_name=address.name or "", addr_spec=address.email)


def to_mime(message: EmailMessage) -> MIMEMessage:
    """Build a MIME message. ``Bcc`` recipients are deliberately left out of the headers."""
    if message.sender is None:
        raise ValueError("Cannot build MIME for a message without a sender")

    mime = MIMEMessage(policy=policy.SMTP)
    mime["From"] = _header_address(message.sender)
    if message.to:
        mime["To"] = tuple(_header_address(a) for a in message.to)
    if message.cc:
        mime["Cc"] = tuple(_header_address(a) for a in message.cc)
    if message.reply_to:
        mime["Reply-To"] = tuple(_header_address(a) for a in message.reply_to)
    mime["Subject"] = message.subject
    mime["Date"] = formatdate(localtime=True)
    mime["Message-ID"] = make_msgid(domain=message.sender.email.rpartition("@")[2])
    for name, value in message.headers.items():
        mime[name] = value

    if message.text is not None:
        mime.set_content(message.text)
        if message.html is not None:
            mime.add_alternative(message.html, subtype="html")
    elif message.html is not None:
        mime.set_content(message.html, subtype="html")

    html_part = mime.get_body(preferencelist=("html",)) if message.html is not None else None
    for attachment in message.attachments:
        maintype, _, subtype = (attachment.content_type or "application/octet-stream").partition(
            "/"
        )
        if attachment.content_id and html_part is not None:
            html_part.add_related(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                cid=f"<{attachment.content_id}>",
                filename=attachment.filename,
                disposition="inline",
            )
        else:
            mime.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )
    return mime
