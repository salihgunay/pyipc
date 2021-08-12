import asyncio
import websockets
from itertools import count
from pickle import loads, dumps
from typing import Dict, Tuple

MAX_MSG_ID = 2 ** 32
MAX_SIZE = 1_000_000_000
PING_INTERVAL = 10


class MessageObject:
    def __init__(self, function_name_: str, message_id_: int, *args, **kwargs):
        self._function_name = function_name_
        self._message_id = message_id_
        self._args = args
        self._kwargs = kwargs
        self._result = None
        self._error = False

    @property
    def function_name(self):
        return self._function_name

    @property
    def message_id(self) -> int:
        return self._message_id

    @property
    def result(self):
        return self._result

    @result.setter
    def result(self, result):
        self._result = result

    @property
    def args(self) -> Tuple:
        return self._args

    @property
    def kwargs(self) -> Dict:
        return self._kwargs

    @property
    def error(self) -> bool:
        return self._error

    @error.setter
    def error(self, error: bool):
        self._error = error


class AsyncIpcClient:
    _listen_task = None

    def __init__(self, host: str = 'localhost', port: int = 8765, connection_lost_callback=None,
                 client_name: str = None, server_name: str = None):
        self._host = host
        self._port = port
        self._iter = count()
        self.tasks: [Dict, asyncio.Future] = {}
        self.proxy = Proxy(self._send)
        self.ws = None
        self._connection_lost_callback = connection_lost_callback
        self.client_name = client_name
        self.server_name = server_name

    @property
    def connected(self) -> bool:
        if self.ws:
            return self.ws.open
        return False

    async def connect(self):
        self.ws = await websockets.connect(f'ws://{self._host}:{self._port}', max_size=MAX_SIZE, ping_interval=None)
        if not self._listen_task:
            self._listen_task = asyncio.create_task(self.listen())

    async def _resend_tasks(self):
        task: asyncio.Future
        message_object: MessageObject
        print(f"resending {len(self.tasks)} tasks. Client: {self.client_name} - Server: {self.server_name}")
        for task, message_object in self.tasks.values():
            await self.ws.send(dumps(message_object))

    async def _reconnect(self):
        print(f"reconnecting. Client: {self.client_name} - Server: {self.server_name}")
        await self.disconnect()
        await self.connect()
        await self._resend_tasks()

    async def disconnect(self):
        if self._listen_task and self._listen_task.done():
            self._listen_task = None
        if self.ws.open:
            await self.ws.close()

        if asyncio.iscoroutinefunction(self._connection_lost_callback):
            await self._connection_lost_callback()
        elif callable(self._connection_lost_callback):
            self._connection_lost_callback()

    async def listen(self):
        try:
            async for message in self.ws:
                message_object: MessageObject = loads(message)
                asyncio.ensure_future(self._on_message(message_object))
        except websockets.ConnectionClosedError as e:
            print(f"Connection Closed Error in client _listen: {e}. Client: {self.client_name} - Server: {self.server_name}")
        except Exception as e:
            print(f"Other Exception in client _listen: {e}. Client: {self.client_name} - Server: {self.server_name}")
        asyncio.ensure_future(self._reconnect())

    async def _on_message(self, message_object: MessageObject):
        future, message_object_ = self.tasks.pop(message_object.message_id)
        if future.done():
            return

        if message_object.error:
            future.set_exception(message_object.result)
        else:
            future.set_result(message_object.result)

    async def _send(self, message_object: MessageObject):
        future = asyncio.Future()
        try:
            self.tasks[message_object.message_id] = (future, message_object)
            if self.connected:
                await self.ws.send(dumps(message_object))
        except (websockets.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK) as e:
            #print(f"Connection Closed Error in client _send: {e}")
            pass  # if Connection error happens reconnecting with listen
        except KeyError as e:
            print(f"Key Error in client _send: {e}")
        except Exception as e:
            print(f"Other Exception in client _send: {e}")
        return await future


class AsyncIpcServer:

    def __init__(self, klass, ws, server_name: str = None):
        self.ws = ws
        self.klass = klass
        self.server_name = server_name

    @property
    def connected(self) -> bool:
        return not self.ws.closed

    async def disconnect(self):
        await self.ws.close()

    async def listen(self):
        try:
            async for message in self.ws:
                message_object: MessageObject = loads(message)
                asyncio.ensure_future(self._on_message(message_object))
        except websockets.ConnectionClosedError as e:
            print(f"Connection Closed Error in server _listen: {e}. Server: {self.server_name}")
            pass  # Wait for client to reconnect
        except Exception as e:
            print(f"Other Exception in server listen: {e}. Server: {self.server_name}")

    async def _on_message(self, message_object: MessageObject):
        result = None
        try:
            func = getattr(self.klass, message_object.function_name)
            result = await func(*message_object.args, **message_object.kwargs) if \
                asyncio.iscoroutinefunction(func) else func(*message_object.args, **message_object.kwargs)
        except Exception as e:
            message_object.error = True
            result = e
        finally:
            message_object.result = result
        try:
            if self.connected:
                await self.ws.send(dumps(message_object))
        except (websockets.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK) as e:
            print(f"server _on_message {e}. Server: {self.server_name}")
            pass  # Connection lost, delete instance and wait for another connection


class Proxy:
    def __init__(self, send):
        self._send = send
        self._iter = count()

    @property
    def _next_message_id(self) -> int:
        message_id = next(self._iter)
        if message_id > MAX_MSG_ID:
            self._iter = count()
        return message_id

    def __getattr__(self, function_name_):
        async def func(*args, **kwargs):
            message_object = MessageObject(function_name_, self._next_message_id, *args, **kwargs)
            return await self._send(message_object)
        return func
