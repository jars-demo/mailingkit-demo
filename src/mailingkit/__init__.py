"""MailingKit: a drop-in, provider-agnostic transactional email layer for Python.

::

    from mailingkit import MailingKit

    mail = MailingKit.from_env()
    await mail.send(to="ada@example.com", subject="Welcome", text="Hello Ada")
"""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("mailingkit")
except PackageNotFoundError:  # pragma: no cover (running from a source checkout)
    __version__ = "0.0.0"

__all__ = [
    "__version__",
]
