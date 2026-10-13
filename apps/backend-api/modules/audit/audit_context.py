from contextvars import ContextVar, Token


_request_ip: ContextVar[str | None] = ContextVar("audit_request_ip", default=None)


def set_audit_request_ip(ip: str | None) -> Token:
    return _request_ip.set(ip)


def reset_audit_request_ip(token: Token) -> None:
    _request_ip.reset(token)


def get_audit_request_ip() -> str | None:
    return _request_ip.get()
