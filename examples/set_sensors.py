from homeassistant_api import Client
from homeassistant_api import State

with Client(
    "http://homeassistant.local:8123/api",
    "myfabulousapikey",
) as client:
    new_state = client.set_state(
        State.model_validate(
            {
                "entity_id": "sensor.some_variable",
                "state": "42 the answer to everything",
            },
        ),
    )
    print(new_state)  # noqa: T201
