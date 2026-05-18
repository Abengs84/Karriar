"""Kontrollera om klient-IP tillhör Finland (CIDR-lista)."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path

from starlette.requests import Request

_IPV4_NETS: list[ipaddress.IPv4Network] = []
_IPV6_NETS: list[ipaddress.IPv6Network] = []
_LOADED = False


def finland_only_enabled() -> bool:
    return os.getenv("KARRIAR_FINLAND_IP_ONLY", "true").lower() in (
        "1",
        "true",
        "yes",
    )


def allow_local_ips() -> bool:
    return os.getenv("KARRIAR_GEOIP_ALLOW_LOCAL", "true").lower() in (
        "1",
        "true",
        "yes",
    )


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def load_fi_networks() -> None:
    global _LOADED, _IPV4_NETS, _IPV6_NETS
    if _LOADED:
        return
    if not finland_only_enabled():
        _LOADED = True
        return

    v4_path = Path(os.getenv("KARRIAR_FI_IPV4_CIDR", _data_dir() / "fi-ipv4.cidr"))
    v6_path = Path(os.getenv("KARRIAR_FI_IPV6_CIDR", _data_dir() / "fi-ipv6.cidr"))

    if not v4_path.is_file():
        raise RuntimeError(
            f"Finland IP-lista saknas: {v4_path}. "
            "Kör Docker-build eller ladda ner fi-ipv4.cidr."
        )

    _IPV4_NETS = _read_cidrs(v4_path, 4)
    if v6_path.is_file():
        _IPV6_NETS = _read_cidrs(v6_path, 6)
    _LOADED = True


def _read_cidrs(path: Path, version: int) -> list:
    nets: list = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        net = ipaddress.ip_network(line, strict=False)
        if net.version != version:
            continue
        nets.append(net)
    return nets


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def _is_local_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
    )


def is_finnish_ip(ip: str) -> bool:
    if not finland_only_enabled():
        return True

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    if allow_local_ips() and _is_local_ip(addr):
        return True

    if isinstance(addr, ipaddress.IPv4Address):
        return any(addr in net for net in _IPV4_NETS)
    return any(addr in net for net in _IPV6_NETS)


def is_request_from_finland(request: Request) -> bool:
    return is_finnish_ip(client_ip(request))
