import asyncio
import os

from homeassistant_api import Client

url = os.getenv("HOMEASSISTANT_API_ENDPOINT")
token = os.getenv("HOMEASSISTANT_API_TOKEN")


async def main() -> None:
    # Initialize main object
    if url is None:
        msg = "Must set HOMEASSISTANT_API_ENDPOINT env variable to continue"
        raise ValueError(msg)
    if token is None:
        msg = "Must set HOMEASSISTANT_API_TOKEN env variable to continue"
        raise ValueError(msg)
    client = Client(url, token, use_async=True)
    # Uses async context manager to ping the server and initialize caching.
    async with client:
        # All async methods are prefixed with `async_`.
        data = await client.async_get_entities()
        print(data)  # noqa: T201


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
