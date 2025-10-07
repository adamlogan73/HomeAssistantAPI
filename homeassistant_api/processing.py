"""Module for processing API responses from homeassistant."""

import inspect
import json
import logging
from collections.abc import Callable
from http import HTTPStatus
from typing import Any
from typing import ClassVar

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
    _decode_bytes: bool
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

    def process_content(self, *, async_: bool = False) -> Any:  # noqa: ANN401
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

    @staticmethod
    def get_status(status_code: int) -> HTTPStatus:
        try:
            return HTTPStatus(status_code)
        except ValueError:
            raise UnexpectedStatusCodeError(status_code) from None

    async def process_async(self) -> Any:  # noqa: ANN401
        if isinstance(self._response, (ClientResponse, AsyncCachedResponse)):
            status = self.get_status(status_code=self._response.status)
            if status not in (HTTPStatus.OK, HTTPStatus.CREATED):
                content = await self._response.content.read()
                return self._process_error_response(
                    raw_content=content,
                    async_=True,
                    status=status,
                )
            data = self.process_content(async_=True)
            return await data
        raise TypeError

    def process(self) -> Any:  # noqa: ANN401
        if isinstance(self._response, (Response, CachedResponse)):
            status = self.get_status(status_code=self._response.status_code)
            if status not in (HTTPStatus.OK, HTTPStatus.CREATED):
                content = self._response.content
                return self._process_error_response(
                    raw_content=content,
                    async_=False,
                    status=status,
                )
            return self.process_content(async_=False)
        raise TypeError

    def _process_error_response(
        self,
        raw_content: str | bytes,
        status: HTTPStatus,
        *,
        async_: bool,
    ) -> Any:  # noqa: ANN401
        """Validates the http status code before starting to process the repsonse content"""
        if self._decode_bytes and isinstance(raw_content, bytes):
            content = raw_content.decode()
        else:
            content = str(raw_content)
        if status == HTTPStatus.BAD_REQUEST:
            raise RequestError(content, url=str(self._response.url))
        if status == HTTPStatus.UNAUTHORIZED:
            raise UnauthorizedError
        if status == HTTPStatus.NOT_FOUND:
            raise EndpointNotFoundError(str(self._response.url))
        if status == HTTPStatus.METHOD_NOT_ALLOWED:
            if not async_:
                method = self._response.request.method  # type: ignore[union-attr]
            else:
                method = self._response.method  # type: ignore[union-attr]
            raise MethodNotAllowedError(str(method))
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise InternalServerError(status.value, content)
        raise UnexpectedStatusCodeError(status.value) from None


# List of default processors
@Processing.processor("application/json")  # type: ignore[arg-type]
def process_json(response: ResponseType) -> dict[str, JSONType] | list[dict]:
    """Returns the json dict content of the response."""
    try:
        data = response.json()
    except (json.JSONDecodeError, simplejson.JSONDecodeError) as err:
        msg = f"Home Assistant responded with non-json response: {response.text!r}"
        raise MalformedDataError(msg) from err
    if not isinstance(data, (dict, list)):
        raise TypeError
    return data


@Processing.processor("text/plain")  # type: ignore[arg-type]
@Processing.processor("application/octet-stream")  # type: ignore[arg-type]
def process_text(response: ResponseType) -> str:
    """Returns the plaintext of the reponse."""
    return response.text


@Processing.processor("application/json")  # type: ignore[arg-type]
async def async_process_json(
    response: AsyncResponseType,
) -> dict[str, JSONType] | list[dict]:
    """Returns the json dict content of the response."""
    try:
        data = await response.json()
    except (json.JSONDecodeError, simplejson.JSONDecodeError) as err:
        msg = f"Home Assistant responded with non-json response: {await response.text()!r}"
        raise MalformedDataError(msg) from err
    if not isinstance(data, (dict, list)):
        raise TypeError
    return data


@Processing.processor("text/plain")  # type: ignore[arg-type]
@Processing.processor("application/octet-stream")  # type: ignore[arg-type]
async def async_process_text(response: AsyncResponseType) -> str:
    """Returns the plaintext of the reponse."""
    return await response.text()
