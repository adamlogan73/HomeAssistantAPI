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
        cover = client.get_domain("cover")
        if cover is None:
            msg = "Did not get a cover domain."
            raise ValueError(msg)

        # Tells Home Assistant to trigger the toggle service on the given entity_id
        cover.toggle(entity_id="cover.garage_door")


main()
