"""Module for the History model."""

from pydantic import Field

from homeassistant_api.models.base import BaseModel
from homeassistant_api.models.states import State


class History(BaseModel):
    """Model representing past :py:class:`State`'s of an entity."""

    states: tuple[State, ...] = Field(
        ...,
        description="A tuple of previous states of an entity.",
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.entity_id is None:
            msg = "Invalid entity_id"
            raise ValueError(msg)

    @property
    def entity_id(self) -> str:
        """Returns the shared :code:`entity_id` of states."""
        entity_ids = [state.entity_id for state in self.states]
        result, *_ = set(entity_ids)
        return result
