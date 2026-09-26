"""Callback delivery helpers for development ML mocks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

import httpx


CallbackSender = Callable[[str, bytes, Mapping[str, str]], int]


def make_in_process_callback_sender(app: object) -> CallbackSender:
    """Route a mock callback through the real ASGI app without opening a socket."""

    def send(url: str, content: bytes, headers: Mapping[str, str]) -> int:
        parsed = urlsplit(url)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"

        async def post() -> int:
            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://pipeline.local",
                timeout=5.0,
            ) as client:
                response = await client.post(target, content=content, headers=headers)
            return response.status_code

        return asyncio.run(post())

    return send
