"""Module for interacting with Home Assistant asyncronously."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from posixpath import join
from types import TracebackType
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import cast

import aiohttp
import aiohttp_client_cache.session
from typing_extensions import Self

from homeassistant_api.errors import BadTemplateError
from homeassistant_api.errors import RequestError
from homeassistant_api.errors import RequestTimeoutError
from homeassistant_api.models import Domain
from homeassistant_api.models import Entity
from homeassistant_api.models import Event
from homeassistant_api.models import Group
from homeassistant_api.models import History
from homeassistant_api.models import LogbookEntry
from homeassistant_api.models import State
from homeassistant_api.processing import AsyncResponseType
from homeassistant_api.processing import Processing
from homeassistant_api.rawbaseclient import RawBaseClient
from homeassistant_api.utils import JSONType
from homeassistant_api.utils import prepare_entity_id

if TYPE_CHECKING:
    from homeassistant_api import Client
else:
    Client = object

logger = logging.getLogger(__name__)


class RawAsyncClient(RawBaseClient):
    """
    The async equivalent of :py:class:`RawClient`

    :param api_url: The location of the api endpoint. e.g. :code:`http://localhost:8123/api` Required.
    :param token: The refresh or long lived access token to authenticate your requests. Required.
    :param global_request_kwargs: A dictionary or dict-like object of kwargs to pass to :func:`requests.request` or :meth:`aiohttp.request`. Optional.
    """  # pylint: disable=line-too-long

    async_cache_session: (
        aiohttp_client_cache.session.CachedSession | aiohttp.ClientSession
    )

    def __init__(
        self,
        *args: Any,  # noqa: ANN401
        async_cache_session: Literal[False]
        | None
        | aiohttp_client_cache.session.CachedSession = None,  # Explicitly disable cache with async_cache_session=False
        verify_ssl: bool = True,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        RawBaseClient.__init__(self, *args, **kwargs)
        connector = aiohttp.TCPConnector(verify_ssl=False) if not verify_ssl else None
        if async_cache_session is False:
            self.async_cache_session = aiohttp.ClientSession(connector=connector)
        elif async_cache_session is None:
            self.async_cache_session = aiohttp_client_cache.CachedSession(  # type: ignore[attr-defined]
                cache=aiohttp_client_cache.CacheBackend(  # type: ignore[attr-defined]
                    cache_name="default_async_cache",
                    expire_after=300,
                ),
                connector=connector,
            )
        elif isinstance(
            async_cache_session,
            aiohttp_client_cache.session.CachedSession,
        ):
            self.async_cache_session = async_cache_session

    async def __aenter__(self) -> Self:
        logger.debug(
            "Entering cached async requests session %r",
            self.async_cache_session,
        )
        await self.async_cache_session.__aenter__()
        try:
            await self.async_check_api_running()
        except Exception:
            await self.async_cache_session.close()
            raise
        return self

    async def __aexit__(
        self,
        _: type[BaseException] | None,
        __: BaseException | None,
        ___: TracebackType | None,
    ) -> None:
        logger.debug("Exiting async requests session %r", self.async_cache_session)
        await self.async_cache_session.close()

    # Very important request function
    async def async_request(
        self,
        path: str,
        *,
        params: str = "",  # should be a string of query parameters from construct_params()
        method: str = "GET",
        headers: dict[str, str] | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Base method for making requests to the api"""
        if self.global_request_kwargs is not None:
            kwargs.update(self.global_request_kwargs)
        try:
            async with self.async_cache_session.request(
                method,
                self.endpoint(path) + f"?{params}" * bool(params),
                headers=self.prepare_headers(headers),
                **kwargs,
            ) as request:
                return await self.async_response_logic(request)

        except asyncio.exceptions.TimeoutError as err:
            msg = f"Home Assistant did not respond in time (timeout: {kwargs.get('timeout', 300)} sec)"
            raise RequestTimeoutError(
                msg,
                self.endpoint(path) + f"?{params}" * bool(params),
            ) from err

    @staticmethod
    async def async_response_logic(response: AsyncResponseType) -> Any:  # noqa: ANN401
        """Processes custom mimetype content asyncronously."""
        return await Processing(response=response).process_async()

    # API information methods
    async def async_get_error_log(self) -> str:
        """
        Returns the server error log as a string.
        :code:`GET /api/error_log`
        """
        return cast("str", await self.async_request("error_log"))

    async def async_get_config(self) -> dict[str, JSONType]:
        """
        Returns the yaml configuration of homeassistant.
        :code:`GET /api/config`
        """
        return cast("dict[str, JSONType]", await self.async_request("config"))

    async def async_get_logbook_entries(
        self,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> AsyncGenerator[LogbookEntry, None]:
        """
        Returns a list of logbook entries from homeassistant.
        :code:`GET /api/logbook/<timestamp>`
        """
        params, url = self.prepare_get_logbook_entry_params(*args, **kwargs)
        data = await self.async_request(
            url,
            params=self.construct_params(cast("dict[str, str | None]", params)),
        )
        for entry in data:
            yield LogbookEntry.model_validate(entry)

    async def async_get_entity_histories(
        self,
        entities: tuple[Entity, ...] | None = None,
        start_timestamp: datetime | None = None,
        # Defaults to 1 day before. https://developers.home-assistant.io/docs/api/rest/
        end_timestamp: datetime | None = None,
        *,
        significant_changes_only: bool = False,
    ) -> AsyncGenerator[History, None]:
        """
        Returns a generator of entity state histories from homeassistant.
        :code:`GET /api/history/period/<timestamp>`
        """
        params, url = self.prepare_get_entity_histories_params(
            entities=entities,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            significant_changes_only=significant_changes_only,
        )
        data = await self.async_request(
            url,
            params=self.construct_params(params),
        )
        for states in data:
            yield History.model_validate({"states": states})

    async def async_get_rendered_template(self, template: str) -> str:
        """
        Renders a given Jinja2 template string with Home Assistant context data.
        :code:`POST /api/template`
        """
        try:
            return cast(
                "str",
                await self.async_request(
                    "template",
                    json={"template": template},
                    method="POST",
                ),
            )
        except RequestError as err:
            msg = (
                "Your template is invalid. "
                "Try debugging it in the developer tools page of homeassistant."
            )
            raise BadTemplateError(msg) from err

    # API check methods
    async def async_check_api_config(self) -> bool:
        """
        Asks Home Assistant to validate its configuration file and returns true/false.
        :code:`POST /api/config/core/check_config`
        """
        res = await self.async_request("config/core/check_config", method="POST")
        res = cast("dict[Any, Any]", res)
        return {"valid": True, "invalid": False}.get(cast("str", res["result"]), False)

    async def async_check_api_running(self) -> bool:
        """
        Asks Home Assistant if its running.
        :code:`GET /api/`
        """
        res = await self.async_request("")
        if not isinstance(res, dict):
            raise TypeError
        return res.get("message") == "API running."

    # Entity methods
    async def async_get_entities(self) -> dict[str, Group]:
        """
        Fetches all entities from the api.
        :code:`GET /api/states`
        """
        entities: dict[str, Group] = {}
        for state in await self.async_get_states():
            group_id, entity_slug = state.entity_id.split(".")
            if group_id not in entities:
                entities[group_id] = Group(group_id=group_id, _client=self)  # type: ignore[arg-type]
            entities[group_id].add_entity(entity_slug, state)
        return entities

    async def async_get_entity(
        self,
        group_id: str | None = None,
        slug: str | None = None,
        entity_id: str | None = None,
    ) -> Entity | None:
        """
        Returns a Entity model for an :code:`entity_id`.
        :code:`GET /api/states/<entity_id>`
        """
        if group_id is not None and slug is not None:
            state = await self.async_get_state(group_id=group_id, slug=slug)
        elif entity_id is not None:
            state = await self.async_get_state(entity_id=entity_id)
        else:
            help_msg = (
                "Use keyword arguments to pass entity_id. "
                "Or you can pass the group_id and slug instead."
            )
            msg = f"Neither group_id and slug or entity_id provided. {help_msg}"
            raise ValueError(msg)
        group_id, entity_slug = state.entity_id.split(".")
        group = Group(group_id=group_id, _client=self)  # type: ignore[arg-type]
        group.add_entity(entity_slug, state)
        return group.get_entity(entity_slug)

    # Services and domain methods
    async def async_get_domains(self) -> dict[str, Domain]:
        """
        Fetches all :py:class:`Service` 's from the API.
        :code:`GET /api/services`
        """
        data = await self.async_request("services")
        domains = (
            Domain.from_json(datum, client=cast("Client", self))
            for datum in cast("tuple[dict[str, JSONType], ...]", data)
        )
        return {domain.domain_id: domain for domain in domains}

    async def async_get_domain(self, domain_id: str) -> Domain | None:
        """
        Fetches all :py:class:`Service`'s under a particular service :py:class:`Domain`.
        Uses cached data from :py:meth:`get_domains` if available.
        """
        domains = await self.async_get_domains()
        return domains.get(domain_id)

    async def async_trigger_service(
        self,
        domain: str,
        service: str,
        **service_data: dict[str, JSONType] | list[Any] | str,
    ) -> tuple[State, ...]:
        """
        Tells Home Assistant to trigger a service, returns all states changed while in the process of being called.
        :code:`POST /api/services/<domain>/<service>`
        """
        data = await self.async_request(
            f"services/{domain}/{service}",
            method="POST",
            json=service_data,
        )
        return tuple(map(State.from_json, cast("list[dict[Any, Any]]", data)))

    async def async_trigger_service_with_response(
        self,
        domain: str,
        service: str,
        **service_data: dict[str, JSONType] | list[Any] | str,
    ) -> tuple[tuple[State, ...], dict[str, JSONType]]:
        """
        Tells Home Assistant to trigger a service, returns the response from the service call.
        :code:`POST /api/services/<domain>/<service>`

        Returns a list of the states changed and the response from the service call.
        """
        data = cast(
            "dict[str, dict[str, JSONType]]",
            await self.async_request(
                join("services", domain, service) + "?return_response",
                method="POST",
                json=service_data,
            ),
        )
        states = tuple(
            map(
                State.from_json,
                cast("list[dict[Any, Any]]", data.get("changed_states", [])),
            ),
        )
        return states, data.get("service_response", {})

    # EntityState methods
    async def async_get_state(  # pylint: disable=duplicate-code
        self,
        *,
        entity_id: str | None = None,
        group_id: str | None = None,
        slug: str | None = None,
    ) -> State:
        """
        Fetches the state of the entity specified.
        :code:`GET /api/states/<entity_id>`
        """
        target_entity_id = prepare_entity_id(
            group_id=group_id,
            slug=slug,
            entity_id=entity_id,
        )
        data = await self.async_request(join("states", target_entity_id))
        return State.from_json(cast("dict[Any, Any]", data))

    async def async_set_state(  # pylint: disable=duplicate-code
        self,
        state: State,
    ) -> State:
        """
        This method sets the representation of a device within Home Assistant and will not communicate with the actual device.
        To communicate with the device, use :py:meth:`Service.trigger` or :py:meth:`Service.async_trigger`.
        :code:`POST /api/states/<entity_id>`
        """
        data = await self.async_request(
            join("states", state.entity_id),
            method="POST",
            json=json.loads(state.model_dump_json()),
        )
        return State.from_json(cast("dict[Any, Any]", data))

    async def async_get_states(self) -> tuple[State, ...]:
        """
        Gets the states of all entities within homeassistant.
        :code:`GET /api/states`
        """
        data = await self.async_request("states")
        return tuple(map(State.from_json, cast("list[dict[Any, Any]]", data)))

    # Event methods
    async def async_get_events(self) -> tuple[Event, ...]:
        """
        Gets the Events that happen within homeassistant
        :code:`GET /api/events`
        """
        data = await self.async_request("events")
        return tuple(
            (
                Event.from_json(datum, client=cast("Client", self))
                for datum in cast("list[dict[str, JSONType]]", data)
            ),
        )

    async def async_get_event(self, name: str) -> Event | None:
        """
        Gets the :py:class:`Event` with the specified name if it has at least one listener.
        Uses cached data from :py:meth:`get_events` if available.
        """
        for event in await self.async_get_events():
            if event.event == name.strip().lower():
                return event
        return None

    async def async_fire_event(self, event_type: str, **event_data: Any) -> str:  # noqa: ANN401
        """
        Fires a given event_type within homeassistant. Must be an existing event_type.
        :code:`POST /api/events/<event_type>`
        """
        data = await self.async_request(
            join("events", event_type),
            method="POST",
            json=event_data,
        )
        return cast("str", data.get("message", "No message provided"))

    async def async_get_components(self) -> tuple[str, ...]:
        """
        Returns a tuple of all registered components.
        :code:`GET /api/components`
        """
        data = await self.async_request("components")
        return tuple(cast("list[str]", data))
