import logging
import os
from collections.abc import AsyncGenerator
from collections.abc import Generator

import pytest
import pytest_asyncio

from homeassistant_api import Client
from homeassistant_api import WebsocketClient

logging.basicConfig(level=logging.INFO)

TIMEOUT = 300


@pytest.fixture(name="wait_for_server", scope="session")
def wait_for_server_fixture() -> None:
    """Waits for the server to be ready."""
    client = Client(
        os.environ["HOMEASSISTANTAPI_URL"],
        os.environ["HOMEASSISTANTAPI_TOKEN"],
    )
    logging.info("Waiting for server to be ready...")
    client.request(method="get", path="", timeout=TIMEOUT)
    logging.info("Server is ready.")


@pytest.fixture(name="cached_client", scope="session")
def setup_cached_client(wait_for_server) -> Generator[Client, None, None]:
    """Initializes the Client and enters a cached session."""
    with Client(
        os.environ["HOMEASSISTANTAPI_URL"],
        os.environ["HOMEASSISTANTAPI_TOKEN"],
    ) as client:
        yield client


@pytest_asyncio.fixture(name="async_cached_client")
async def setup_async_cached_client(
    wait_for_server: None,
) -> AsyncGenerator[Client, None]:
    """Initializes the Client and enters an async cached session."""
    async with Client(
        os.environ["HOMEASSISTANTAPI_URL"],
        os.environ["HOMEASSISTANTAPI_TOKEN"],
        use_async=True,
    ) as client:
        yield client


@pytest.fixture(name="websocket_client", scope="session")
def setup_websocket_client(
    wait_for_server: None,
) -> Generator[Client, None, None]:
    """Initializes the Client and enters a WebSocket session."""
    with WebsocketClient(
        os.environ["HOMEASSISTANTAPI_WS_URL"],
        os.environ["HOMEASSISTANTAPI_TOKEN"],
    ) as client:
        yield client
