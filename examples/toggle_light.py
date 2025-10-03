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


def main() -> None:
    api_url, token = get_api_info_from_environment()
    # Verifies the existence of the specified server and opens efficient ClientSessions.
    with Client(api_url, token) as client:
        # Gets the cover service domain
        light = client.get_domain("light")
        if light is None:
            msg = "Did not get light group from home assistant."
            raise ValueError(msg)

        # Triggers the service with a specific garage door
        print(light.toggle(entity_id="light.light_bulb_1"))  # noqa: T201


main()
