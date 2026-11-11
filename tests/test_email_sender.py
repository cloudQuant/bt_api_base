"""SMTP behavior is tested with a fake; these tests make no network calls."""

import importlib
import smtplib
import ssl

import pytest

from bt_api_base import email_sender


class FakeSMTP:
    def __init__(self, *args, **kwargs):
        self.events = [("connect", args, kwargs)]
        self.refused = {}
        self.failure = None

    def ehlo(self):
        self.events.append(("ehlo",))
        return 250, b"hello"

    def starttls(self, *, context):
        self.events.append(("starttls", context))

    def login(self, username, password):
        self.events.append(("login", username, password))
        if self.failure:
            raise self.failure

    def send_message(self, message, *, from_addr, to_addrs):
        self.events.append(("send", message, from_addr, to_addrs))
        if self.failure:
            raise self.failure
        return self.refused

    def close(self):
        self.events.append(("close",))


@pytest.fixture
def transport(monkeypatch):
    instances = []

    def factory(*args, **kwargs):
        instance = FakeSMTP(*args, **kwargs)
        instances.append(instance)
        return instance

    monkeypatch.setattr(email_sender.smtplib, "SMTP", factory)
    monkeypatch.setattr(email_sender.smtplib, "SMTP_SSL", factory)
    return instances


def send(**changes):
    options = {
        "host": "mail.example.test",
        "port": 587,
        "timeout": 5,
        "sender": "sender@example.test",
        "recipients": ["a@example.test", "b@example.test"],
        "subject": "中文主题",
        "body": "第一行\n第二行",
    }
    options.update(changes)
    return email_sender.send_email(**options)


def test_default_starttls_auth_and_unicode_message(transport):
    result = send(username="user", password="secret")
    events = transport[0].events
    assert [event[0] for event in events] == [
        "connect", "ehlo", "starttls", "ehlo", "login", "send", "close"
    ]
    assert events[0][1:] == (("mail.example.test", 587), {"timeout": 5})
    assert isinstance(events[2][1], ssl.SSLContext)
    assert events[2][1].verify_mode == ssl.CERT_REQUIRED
    assert events[2][1].check_hostname
    assert events[4][1:] == ("user", "secret")
    _, message, sender, recipients = events[5]
    assert sender == "sender@example.test"
    assert recipients == ("a@example.test", "b@example.test")
    assert str(message["Subject"]) == "中文主题"
    assert str(message["To"]) == "a@example.test, b@example.test"
    assert message.get_content() == "第一行\n第二行\n"
    assert result.accepted_recipients == recipients
    assert result.refused_recipients == {}


def test_ssl_and_explicit_plain_transport(monkeypatch):
    ssl_instances, plain_instances = [], []

    def factory(instances):
        def create(*args, **kwargs):
            client = FakeSMTP(*args, **kwargs)
            instances.append(client)
            return client
        return create

    monkeypatch.setattr(email_sender.smtplib, "SMTP_SSL", factory(ssl_instances))
    monkeypatch.setattr(email_sender.smtplib, "SMTP", factory(plain_instances))
    send(security="ssl", port=465)
    assert [event[0] for event in ssl_instances[0].events] == ["connect", "ehlo", "send", "close"]
    context = ssl_instances[0].events[0][2]["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    send(security="plain", port=25)
    assert [event[0] for event in plain_instances[0].events] == ["connect", "ehlo", "send", "close"]


def test_partial_refusal_is_reported(monkeypatch):
    client = FakeSMTP()
    client.refused = {"b@example.test": (550, b"not accepted")}
    monkeypatch.setattr(email_sender.smtplib, "SMTP", lambda *args, **kwargs: client)
    result = send()
    assert result.accepted_recipients == ("a@example.test",)
    assert result.refused_recipients == {"b@example.test": (550, b"not accepted")}


@pytest.mark.parametrize("failure, credentials", [
    (smtplib.SMTPAuthenticationError(535, b"authentication failed"), True),
    (smtplib.SMTPRecipientsRefused({"a@example.test": (550, b"refused")}), False),
    (OSError("network unavailable"), False),
])
def test_errors_propagate_and_connection_closes(monkeypatch, failure, credentials):
    client = FakeSMTP()
    client.failure = failure
    monkeypatch.setattr(email_sender.smtplib, "SMTP", lambda *args, **kwargs: client)
    with pytest.raises(type(failure)) as raised:
        send(**({"username": "user", "password": "secret"} if credentials else {}))
    assert raised.value is failure
    assert client.events[-1] == ("close",)


def test_connect_error_propagates(monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError("connect timed out")
    monkeypatch.setattr(email_sender.smtplib, "SMTP", fail)
    with pytest.raises(TimeoutError):
        send()


def test_close_failure_preserves_accepted_result(monkeypatch):
    client = FakeSMTP()

    def fail_close():
        raise OSError("close failed")

    client.close = fail_close
    monkeypatch.setattr(email_sender.smtplib, "SMTP", lambda *args, **kwargs: client)
    result = send()
    assert result.accepted_recipients == ("a@example.test", "b@example.test")
    assert result.refused_recipients == {}


def test_close_failure_preserves_original_send_error(monkeypatch):
    client = FakeSMTP()
    failure = smtplib.SMTPDataError(451, b"rejected")
    client.failure = failure

    def fail_close():
        raise OSError("close failed")

    client.close = fail_close
    monkeypatch.setattr(email_sender.smtplib, "SMTP", lambda *args, **kwargs: client)
    with pytest.raises(smtplib.SMTPDataError) as raised:
        send()
    assert raised.value is failure


def test_starttls_failure_does_not_send_or_authenticate(monkeypatch):
    client = FakeSMTP()

    def fail(*, context):
        raise smtplib.SMTPNotSupportedError("STARTTLS unavailable")

    client.starttls = fail
    monkeypatch.setattr(email_sender.smtplib, "SMTP", lambda *args, **kwargs: client)
    with pytest.raises(smtplib.SMTPNotSupportedError):
        send(username="user", password="secret")
    assert [event[0] for event in client.events] == ["connect", "ehlo", "close"]


@pytest.mark.parametrize("changes", [
    {"sender": "x@example.test\nBcc: evil@example.test"},
    {"sender": "bad address"},
    {"sender": "a@example.test,b@example.test"},
    {"recipients": []},
    {"recipients": "a@example.test"},
    {"recipients": ["a@example.test", "a@example.test"]},
    {"recipients": ["a@example.test\r\nBcc: evil@example.test"]},
    {"subject": "hello\r\nBcc: evil@example.test"},
    {"body": None},
    {"host": "mail\n.example.test"},
    {"port": 0}, {"port": True}, {"port": 65536},
    {"timeout": 0}, {"timeout": float("nan")}, {"timeout": float("inf")},
    {"timeout": 86401}, {"timeout": 10**1000}, {"timeout": True},
    {"username": "user"}, {"password": "secret"},
    {"username": "user", "password": ""},
    {"security": "unknown"},
])
def test_invalid_inputs_fail_before_connect(transport, changes):
    with pytest.raises(ValueError):
        send(**changes)
    assert not transport


def test_import_does_not_connect(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("import must not connect")
    monkeypatch.setattr(smtplib, "SMTP", fail)
    monkeypatch.setattr(smtplib, "SMTP_SSL", fail)
    importlib.reload(email_sender)
