import os

from homeassistant_api import Client
from homeassistant_api import State


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
        api_url, token = get_api_info_from_environment()
        new_state = client.set_state(
            State.model_validate(
                {
                    "entity_id": "sensor.some_variable",
                    "state": "42 the answer to everything",
                },
            ),
        )
        print(new_state)  # noqa: T201


main()
