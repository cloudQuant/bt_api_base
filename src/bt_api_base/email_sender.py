"""Explicit, synchronous SMTP delivery of a single plain-text message.

No connection is made until :func:`send_email` is called.  An accepted
recipient means the SMTP server accepted responsibility for the message; it
does not establish delivery to the recipient's mailbox.
"""

from __future__ import annotations

import math
import smtplib
import ssl
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage


@dataclass(frozen=True)
class EmailSendResult:
    """Server acceptance and refusal details, not mailbox delivery evidence."""

    accepted_recipients: tuple[str, ...]
    refused_recipients: dict[str, tuple[int, bytes]]


def _header(value: str, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{name} must be a non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _address(value: str, name: str) -> str:
    value = _header(value, name)
    try:
        parsed = Address(addr_spec=value)
    except (TypeError, ValueError, HeaderParseError) as exc:
        raise ValueError(f"{name} must be a single email address") from exc
    if not parsed.username or not parsed.domain:
        raise ValueError(f"{name} must be a single email address")
    return value


def send_email(
    *,
    host: str,
    port: int,
    timeout: float,
    sender: str,
    recipients: Sequence[str],
    subject: str,
    body: str,
    username: str | None = None,
    password: str | None = None,
    security: str = "starttls",
    return_all_refused: bool = False,
) -> EmailSendResult:
    """Send one plain-text message using ``starttls``, ``ssl``, or ``plain``.

    TLS uses the system's default certificate and hostname verification. The
    ``plain`` mode is unencrypted and must be selected explicitly. Credentials
    are optional but must be supplied together. SMTP and network exceptions are
    propagated; if all recipients are refused, smtplib raises
    ``SMTPRecipientsRefused`` by default. With ``return_all_refused=True``, an
    exception raised by the send itself becomes a refusal result only when it
    contains exactly the requested recipients and valid 4xx/5xx replies.
    Other exceptions continue to propagate. The returned refusal mapping contains the SMTP
    status and server response for each refused recipient. Errors closing the
    local connection do not replace the send result or an earlier exception.
    """
    _header(host, "host")
    if any(char.isspace() for char in host):
        raise ValueError("host must not contain whitespace")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < timeout <= 86400
        or not math.isfinite(timeout)
    ):
        raise ValueError("timeout must be finite and between 0 and 86400 seconds")
    if security not in ("starttls", "ssl", "plain"):
        raise ValueError("security must be 'starttls', 'ssl', or 'plain'")
    if type(return_all_refused) is not bool:
        raise ValueError("return_all_refused must be a bool")
    if (username is None) != (password is None):
        raise ValueError("username and password must be supplied together")
    if username is not None:
        _header(username, "username")
        if not isinstance(password, str) or not password:
            raise ValueError("password must be a non-empty string")
    sender = _address(sender, "sender")
    if isinstance(recipients, (str, bytes)) or not isinstance(recipients, Sequence):
        raise ValueError("recipients must be a non-empty sequence of addresses")
    recipients = tuple(_address(value, "recipient") for value in recipients)
    if not recipients or len(set(recipients)) != len(recipients):
        raise ValueError("recipients must be non-empty and contain no duplicates")
    _header(subject, "subject", allow_empty=True)
    if not isinstance(body, str):
        raise ValueError("body must be a string")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    if security == "ssl":
        client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
    try:
        code, response = client.ehlo()
        if code != 250:
            raise smtplib.SMTPHeloError(code, response)
        if security == "starttls":
            client.starttls(context=ssl.create_default_context())
            code, response = client.ehlo()
            if code != 250:
                raise smtplib.SMTPHeloError(code, response)
        if username is not None:
            client.login(username, password)
        try:
            refused = client.send_message(message, from_addr=sender, to_addrs=recipients)
        except smtplib.SMTPRecipientsRefused as exc:
            refused = exc.recipients
            if (
                not return_all_refused
                or type(refused) is not dict
                or any(type(address) is not str for address in refused)
                or set(refused) != set(recipients)
                or any(
                    type(reply) is not tuple
                    or len(reply) != 2
                    or type(reply[0]) is not int
                    or not 400 <= reply[0] <= 599
                    or type(reply[1]) is not bytes
                    for reply in refused.values()
                )
            ):
                raise
        return EmailSendResult(
            accepted_recipients=tuple(address for address in recipients if address not in refused),
            refused_recipients=dict(refused),
        )
    finally:
        # Cleanup failure cannot change the already observed SMTP outcome.
        with suppress(Exception):
            client.close()
