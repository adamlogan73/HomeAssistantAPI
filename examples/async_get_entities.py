import asyncio
import os

from homeassistant_api import Client


def get_api_info_from_environment() -> tuple[str, str]:
    # Something like http://localhost:8123/api
    api_url = os.getenv("HOMEASSISTANT_API_URL")
    # See the documentation on how to obtain a Long Lived Access Token
    token = os.getenv("HOMEASSISTANT_API_TOKEN")

    if api_url is None:
        msg = "Must set HOMEASSISTANT_API_URL env variable to continue"
        raise ValueError(msg)
    if token is None:
        msg = "Must set HOMEASSISTANT_API_TOKEN env variable to continue"
        raise ValueError(msg)
    return api_url, token


async def main() -> None:
    api_url, token = get_api_info_from_environment()
    client = Client(api_url, token, use_async=True)
    # Uses async context manager to ping the server and initialize caching.
    async with client:
        # All async methods are prefixed with `async_`.
        data = await client.async_get_entities()
        print(data)  # noqa: T201


asyncio.run(main())
