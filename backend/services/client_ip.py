"""Resolve the original client IP from the reverse-proxy request chain."""

from ipaddress import ip_address


def _normalise(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith(("::ffff:", "::FFFF:")):
        value = value[7:]
    try:
        return str(ip_address(value))
    except ValueError:
        return None


def get_client_ip(connection) -> str | None:
    """Prefer the public/global address supplied by the edge proxy.

    Cloudflare's connecting-IP header is authoritative when present. For an
    X-Forwarded-For chain, prefer the first globally routable address so an
    internal proxy address is not stored as the user address.
    """
    cloudflare = _normalise(connection.headers.get("cf-connecting-ip"))
    if cloudflare:
        return cloudflare

    forwarded = [
        ip for part in connection.headers.get("x-forwarded-for", "").split(",")
        if (ip := _normalise(part))
    ]
    for candidate in forwarded:
        if ip_address(candidate).is_global:
            return candidate
    if forwarded:
        return forwarded[0]

    real_ip = _normalise(connection.headers.get("x-real-ip"))
    if real_ip:
        return real_ip

    client = getattr(connection, "client", None)
    if not client:
        return None
    return _normalise(client.host if hasattr(client, "host") else client[0])
