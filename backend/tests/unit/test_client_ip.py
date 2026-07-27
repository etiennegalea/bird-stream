from types import SimpleNamespace

from services.client_ip import get_client_ip


def connection(headers, client=("10.0.0.2", 1234)):
    return SimpleNamespace(headers=headers, client=client)


def test_prefers_cloudflare_connecting_ip():
    request = connection({
        "cf-connecting-ip": "203.0.113.10",
        "x-forwarded-for": "10.0.0.4",
    })
    assert get_client_ip(request) == "203.0.113.10"


def test_prefers_global_address_from_forwarded_chain():
    request = connection({
        "x-forwarded-for": "10.0.0.4, 8.8.8.8, 172.18.0.2",
    })
    assert get_client_ip(request) == "8.8.8.8"


def test_falls_back_to_forwarded_private_address():
    request = connection({"x-forwarded-for": "192.168.1.20, 172.18.0.2"})
    assert get_client_ip(request) == "192.168.1.20"
