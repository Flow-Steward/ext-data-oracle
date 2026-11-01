"""Closed, bounded Oracle inputs and connection values."""

import ipaddress
import json
import re


class Failure(Exception):
    def __init__(self, code, message, *, dispatched=False):
        super().__init__(message)
        self.code = code
        self.dispatched = dispatched


def require(condition, message, *, code="invalid_payload"):
    if not condition:
        raise Failure(code, message)


def text(value, name, maximum=65536, *, nonempty=False):
    require(isinstance(value, str), f"{name} must be text.")
    require(len(value.encode("utf-8")) <= maximum and "\x00" not in value, f"Invalid {name}.")
    require(not nonempty or bool(value.strip()), f"{name} must be nonempty.")
    return value


def integer(value, name, low, high):
    require(
        type(value) is int and low <= value <= high,
        f"{name} must be an integer from {low} to {high}.",
    )
    return value


def boolean(value, name):
    require(type(value) is bool, f"{name} must be boolean.")
    return value


def bounded_json(value, limit=256 * 1024):
    try:
        require(
            len(json.dumps(value, allow_nan=False).encode()) <= limit, "JSON exceeds byte limit."
        )
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise Failure("invalid_payload", "Bounded valid JSON is required.") from exc


def connection_values(connection):
    try:
        config, secrets = connection.get("config") or {}, connection.get("secrets") or {}
        require(
            isinstance(config, dict) and isinstance(secrets, dict), "Invalid connection objects."
        )
        require(
            set(config)
            <= {"host", "port", "tls", "service_name", "allow_writes", "request_timeout_seconds"},
            "Unknown connection setting.",
        )
        require(set(secrets) <= {"username", "password"}, "Unknown credential setting.")
        host = text(config.get("host"), "host", 253, nonempty=True)
        require(
            not any(c.isspace() or c in "/\\@?#[]$%" for c in host),
            "Use a hostname without URL components.",
        )
        if ":" in host:
            ipaddress.IPv6Address(host)
        service = text(config.get("service_name"), "service_name", 128, nonempty=True)
        require(
            re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", service),
            "Invalid Oracle service name.",
        )
        result = {
            "host": host,
            "port": integer(config.get("port", 1521), "port", 1, 65535),
            "tls": boolean(config.get("tls", True), "tls"),
            "service_name": service,
            "allow_writes": boolean(config.get("allow_writes", False), "allow_writes"),
            "request_timeout_seconds": integer(
                config.get("request_timeout_seconds", 15), "request_timeout_seconds", 1, 30
            ),
        }
        for key in ("username", "password"):
            text(secrets.get(key), key, 8192, nonempty=True)
        return result, secrets
    except (Failure, ValueError, TypeError, UnicodeError) as exc:
        raise Failure(
            "invalid_connection", "Invalid Oracle connection configuration or credentials."
        ) from exc
