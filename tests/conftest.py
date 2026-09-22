"""Keep normal tests offline even if a provider mock is accidentally omitted."""

from typing import NoReturn

import httpx
import pytest


@pytest.fixture(autouse=True)
def block_real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_request(*args: object, **kwargs: object) -> NoReturn:
        # pytest's failure bypasses provider exception handling so an accidental
        # network call cannot masquerade as an expected provider failure.
        pytest.fail(
            "Real HTTP is disabled in tests; use a mock transport.", pytrace=False
        )

    async def reject_async_request(*args: object, **kwargs: object) -> NoReturn:
        reject_request()

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject_request)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", reject_async_request
    )
