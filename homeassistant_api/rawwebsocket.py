import json
import logging
import time
from types import TracebackType
from typing import Any
from typing import Self

import websockets.sync.client as ws
from pydantic import ValidationError

from homeassistant_api.errors import ReceivingError
from homeassistant_api.errors import RequestError
from homeassistant_api.errors import ResponseError
from homeassistant_api.errors import UnauthorizedError
from homeassistant_api.models.websocket import AuthInvalid
from homeassistant_api.models.websocket import AuthOk
from homeassistant_api.models.websocket import AuthRequired
from homeassistant_api.models.websocket import ErrorResponse
from homeassistant_api.models.websocket import EventResponse
from homeassistant_api.models.websocket import PingResponse
from homeassistant_api.models.websocket import ResultResponse
from homeassistant_api.utils import JSONType

logger = logging.getLogger(__name__)


class RawWebsocketClient:
    api_url: str
    token: str
    _conn: ws.ClientConnection | None

    def __init__(
        self,
        api_url: str,
        token: str,
    ) -> None:
        self.api_url = api_url
        self.token = token.strip()
        self._conn = None

        self._id_counter = 0
        self._result_responses: dict[
            int,
            ResultResponse | None,
        ] = {}  # id -> response
        self._event_responses: dict[
            int,
            list[EventResponse],
        ] = {}  # id -> [response, ...]
        self._ping_responses: dict[int, PingResponse] = {}  # id -> (sent, received)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.api_url!r})"

    def __enter__(self) -> Self:
        self._conn = ws.connect(self.api_url)
        self._conn.__enter__()
        okay = self.authentication_phase()
        logger.info("Authenticated with Home Assistant (%s)", okay.ha_version)
        self.supported_features_phase()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._conn:
            msg = "Connection is not open!"
            raise ReceivingError(msg)
        self._conn.__exit__(exc_type, exc_value, traceback)
        self._conn = None

    def _request_id(self) -> int:
        """Get a unique id for a message."""
        self._id_counter += 1
        return self._id_counter

    def _send(self, data: dict[str, JSONType]) -> None:
        """Send a message to the websocket server."""
        logger.debug(f"Sending message: {data}")
        if self._conn is None:
            msg = "Connection is not open!"
            raise ReceivingError(msg)
        self._conn.send(json.dumps(data))

    def _recv(self) -> dict[str, JSONType]:
        """Receive a message from the websocket server."""
        if self._conn is None:
            msg = "Connection is not open!"
            raise ReceivingError(msg)
        _bytes = self._conn.recv()
        logger.debug("Received message: %s", _bytes)
        data = json.loads(_bytes)
        if not isinstance(data, dict):
            raise TypeError
        return data

    def send(
        self,
        type_: str,
        *,
        include_id: bool = True,
        **data: Any,  # noqa: ANN401
    ) -> int:
        """
        Send a command message to the websocket server and wait for a "result" response.

        Returns the id of the message sent.
        """
        if include_id:  # auth messages don't have an id
            data["id"] = self._request_id()
        id_ = data.get("id")

        if id_ and not isinstance(id_, int):
            msg = "id should be an int"
            raise ValueError(msg)

        data["type"] = type_
        self._send(data)

        if id_ is None:
            return -1  # non-command messages don't have an id

        if data["type"] == "ping":
            self._ping_responses[id_] = PingResponse(
                start=time.perf_counter_ns(),
                id=id_,
                type="pong",
            )
        else:
            self._event_responses[id_] = []
            self._result_responses[id_] = None
        return id_

    def check_success(self, data: dict[str, JSONType]) -> None:
        """Check if a command message was successful."""
        try:
            error_resp = ErrorResponse.model_validate(data)
            raise RequestError(error_resp.error.code, error_resp.error.message)
        except ValidationError:
            pass

    def handle_recv(self, data: dict[str, JSONType]) -> None:
        """Handle a received message."""
        if "id" not in data:
            msg = "Received a message without an id outside the auth phase."
            raise ReceivingError(msg)
        self.check_success(data)
        self.parse_response(data)

    def parse_response(self, data: dict[str, JSONType]) -> None:
        data_id = data["id"]
        if not isinstance(data_id, int):
            msg = "id must be an int"
            raise TypeError(msg)
        if data.get("type") == "pong":
            logger.info("Received pong message")
            self._ping_responses[data_id].end = time.perf_counter_ns()
        elif data.get("type") == "result":
            logger.info("Received result message")
            if data.get("success"):
                self._result_responses[data_id] = ResultResponse.model_validate(data)
            else:
                error_resp = ErrorResponse.model_validate(data)
                raise RequestError(error_resp.error.code, error_resp.error.message)
        elif data.get("type") == "event":
            logger.info("Received event message %s", data["event"])
            self._event_responses[data_id].append(EventResponse.model_validate(data))
        else:
            msg = f"Received unexpected message type: {data}"
            raise ReceivingError(msg)

    def recv(self, id_: int) -> EventResponse | ResultResponse | PingResponse:
        """Receive a response to a message from the websocket server."""
        while True:
            ## have we received a message with the id we're looking for?
            result_response = self._result_responses.pop(id_, None)
            if result_response is not None:
                return result_response
            event_response = self._event_responses.get(id_)
            if event_response:
                return event_response.pop(0)
            ping_response = self._ping_responses.get(id_)
            if ping_response is not None and ping_response.end is not None:
                return ping_response
            ## if not, keep receiving messages until we do
            self.handle_recv(self._recv())

    def recv_event_response(self, id_: int) -> EventResponse:
        while True:
            response = self.recv(id_)
            if response and isinstance(response, EventResponse):
                return response

    def recv_result_response(self, id_: int) -> ResultResponse:
        while True:
            response = self.recv(id_)
            if response and isinstance(response, ResultResponse):
                return response

    def recv_ping_response(self, id_: int) -> PingResponse:
        while True:
            response = self.recv(id_)
            if response and isinstance(response, PingResponse):
                return response

    def authentication_phase(self) -> AuthOk:
        """Authenticate with the websocket server."""
        # Capture the first message from the server saying we need to authenticate
        try:
            welcome = AuthRequired.model_validate(self._recv())
            logger.debug(f"Received welcome message: {welcome}")
        except ValidationError as e:
            msg = "Unexpected response during authentication"
            raise ResponseError(msg) from e

        # Send our authentication token
        self.send("auth", access_token=self.token, include_id=False)
        logger.debug("Sent auth message")

        # Check the response
        resp = self._recv()
        try:
            return AuthOk.model_validate(resp)
        except ValidationError as e:
            error_resp = AuthInvalid.model_validate(resp)
            raise UnauthorizedError(error_resp.message) from e
        except Exception as e:
            msg = "Unexpected response during authentication"
            raise ResponseError(msg, resp["message"]) from e

    def supported_features_phase(self) -> None:
        """Get the supported features from the websocket server."""
        resp = self.recv_result_response(
            self.send(
                "supported_features",
                features={
                    # "coalesce_messages": 42, # including this key sets it to True  # noqa: ERA001
                },
            ),
        )
        if resp.result is not None:
            msg = "Supported Features response should be None"
            raise ValueError(msg)

    def ping_latency(self) -> float:
        """Get the latency (in milliseconds) of the connection by sending a ping message."""
        pong = self.recv_ping_response(self.send("ping"))
        if pong.end is None:
            msg = "Ping response not received."
            raise ResponseError(msg)
        return (pong.end - pong.start) / 1_000_000
