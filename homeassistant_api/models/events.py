"""Event Model File"""

from typing import TYPE_CHECKING
from typing import Any
from typing import Optional

from pydantic import Field

from homeassistant_api.models.base import BaseModel
from homeassistant_api.utils import JSONType

if TYPE_CHECKING:
    from homeassistant_api import Client


class Event(BaseModel):
    """
    Event class for Home Assistant Event Triggers

    For attribute information see the Data Science docs on Event models
    https://data.home-assistant.io/docs/events
    """

    _client: "Client"
    event: str = Field(..., description="The event name/type.")
    listener_count: int = Field(
        ...,
        description="How many listeners are interesting in this event in Home Assistant.",
    )

    def __init__(
        self,
        *args: Any,  # noqa: ANN401
        _client: Optional["Client"] = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_client", _client)

    def fire(self, **event_data: Any) -> str | None:  # noqa: ANN401
        """Fires the corresponding event in Home Assistant."""
        return self._client.fire_event(self.event, **event_data)

    async def async_fire(self, **event_data: Any) -> str:  # noqa: ANN401
        """Fires the event type in homeassistant. Ex. `on_startup`"""
        return await self._client.async_fire_event(self.event, **event_data)

    @classmethod
    def from_json(cls, json: dict[str, JSONType], client: "Client") -> "Event":
        """Constructs Event model from json data"""
        return cls(**json, _client=client)
