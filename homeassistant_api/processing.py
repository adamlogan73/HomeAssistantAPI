"""Module for processing API responses from homeassistant."""

import inspect
import json
import logging
from collections.abc import Callable
from http import HTTPStatus
from typing import Any
from typing import ClassVar
from typing import cast

import simplejson
from aiohttp import ClientResponse
from aiohttp_client_cache.response import CachedResponse as AsyncCachedResponse
from requests import Response
from requests_cache.models.response import CachedResponse

from homeassistant_api.errors import EndpointNotFoundError
from homeassistant_api.errors import InternalServerError
from homeassistant_api.errors import MalformedDataError
from homeassistant_api.errors import MethodNotAllowedError
from homeassistant_api.errors import ProcessorNotFoundError
from homeassistant_api.errors import RequestError
from homeassistant_api.errors import UnauthorizedError
from homeassistant_api.errors import UnexpectedStatusCodeError
from homeassistant_api.utils import JSONType

logger = logging.getLogger(__name__)


AsyncResponseType = AsyncCachedResponse | ClientResponse
ResponseType = Response | CachedResponse
AllResponseType = AsyncCachedResponse | ClientResponse | Response | CachedResponse
ProcessorType = Callable[[AllResponseType], Any]


class Processing:
    """Uses to processor functions to convert json data into common python data types."""

    _response: AllResponseType
    _processors: ClassVar[dict[str, tuple[ProcessorType, ...]]] = {}

    def __init__(self, response: AllResponseType, *, decode_bytes: bool = True) -> None:
        self._response = response
        self._decode_bytes = decode_bytes

    @staticmethod
    def processor(mimetype: str) -> Callable[[ProcessorType], ProcessorType]:
        """A decorator used to register a response converter function."""

        def register_processor(processor: ProcessorType) -> ProcessorType:
            if mimetype not in Processing._processors:
                Processing._processors[mimetype] = ()
            Processing._processors[mimetype] += (processor,)
            return processor

        return register_processor

    def process_content(self, *, async_: bool = False) -> Any:
        """
        Looks up processors by their Content-Type header and then
        calls the processor with the response.
        """

        mimetype_header = self._response.headers.get(
            "content-type",
            "text/plain",
        )
        mimetype = mimetype_header.split(";")[0]
        for processor in self._processors.get(mimetype, ()):
            if not async_ ^ inspect.iscoroutinefunction(processor):
                logger.debug("Using processor %r on %r", processor, self._response)
                return processor(self._response)
        msg = f"No response processor found for mimetype {mimetype!r}."
        raise ProcessorNotFoundError(msg)

    def process(self) -> Any:  # noqa: C901
        """Validates the http status code before starting to process the repsonse content"""
        raw_content: str | bytes
        sync_response: bool = False
        if async_response := isinstance(
            self._response,
            (ClientResponse, AsyncCachedResponse),
        ):
            status_code = self._response.status
            _buffer = self._response.content._buffer
            raw_content = b"" if not _buffer else _buffer[0]
        elif sync_response := isinstance(self._response, (Response, CachedResponse)):
            status_code = self._response.status_code
            raw_content = self._response.content
        else:
            msg = f"Unsupported response type: {type(self._response).__name__}"
            raise TypeError(msg)

        try:
            status = HTTPStatus(status_code)
        except ValueError:
            raise UnexpectedStatusCodeError(status_code) from None

        if self._decode_bytes and isinstance(raw_content, bytes):
            content = raw_content.decode()
        else:
            content = str(raw_content)
        if status in (HTTPStatus.OK, HTTPStatus.CREATED):
            return self.process_content(async_=async_response)
        if status == HTTPStatus.BAD_REQUEST:
            raise RequestError(content, url=str(self._response.url))
        if status == HTTPStatus.UNAUTHORIZED:
            raise UnauthorizedError
        if status == HTTPStatus.NOT_FOUND:
            raise EndpointNotFoundError(str(self._response.url))
        if status == HTTPStatus.METHOD_NOT_ALLOWED:
            if sync_response:
                method = self._response.request.method  # type: ignore[union-attr]
            else:
                method = self._response.method  # type: ignore[union-attr]
            raise MethodNotAllowedError(cast("str", method))
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise InternalServerError(status.value, content)
        return None


# List of default processors
@Processing.processor("application/json")  # type: ignore[arg-type]
def process_json(response: ResponseType) -> dict[str, JSONType]:
    """Returns the json dict content of the response."""
    try:
        return cast("dict[str, JSONType]", response.json())
    except (json.JSONDecodeError, simplejson.JSONDecodeError) as err:
        msg = f"Home Assistant responded with non-json response: {response.text!r}"
        raise MalformedDataError(msg) from err


@Processing.processor("text/plain")  # type: ignore[arg-type]
@Processing.processor("application/octet-stream")  # type: ignore[arg-type]
def process_text(response: ResponseType) -> str:
    """Returns the plaintext of the reponse."""
    return response.text


@Processing.processor("application/json")  # type: ignore[arg-type]
async def async_process_json(response: AsyncResponseType) -> dict[str, JSONType]:
    """Returns the json dict content of the response."""
    try:
        return cast("dict[str, JSONType]", await response.json())
    except (json.JSONDecodeError, simplejson.JSONDecodeError) as err:
        msg = f"Home Assistant responded with non-json response: {await response.text()!r}"
        raise MalformedDataError(msg) from err


@Processing.processor("text/plain")  # type: ignore[arg-type]
@Processing.processor("application/octet-stream")  # type: ignore[arg-type]
async def async_process_text(response: AsyncResponseType) -> str:
    """Returns the plaintext of the reponse."""
    return await response.text()
