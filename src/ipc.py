import asyncio
import websockets
from itertools import count
from pickle import loads, dumps
from typing import Dict, Tuple

MAX_MSG_ID = 2 ** 32
MAX_SIZE = 1_000_000_000
PING_INTERVAL = 10


class MessageObject:
    def __init__(self, function_name: str, message_id: int, *args,  result=None, **kwargs):
        self._function_name = function_name
        self._message_id = message_id
        self._args = args
        self._kwargs = kwargs
        self._result = result
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
    _auto_ping_task = None

    def __init__(self, host: str = 'localhost', port: int = 8765):
        self._host = host
        self._port = port
        self._iter = count()
        self.tasks: [Dict, asyncio.Future] = {}
        self.proxy = Proxy(self._send)
        self.ws = None

    async def connect(self):
        self.ws = await websockets.connect(f'ws://{self._host}:{self._port}', max_size=MAX_SIZE, ping_interval=None)
        self._listen_task = asyncio.create_task(self.listen())
        self._auto_ping_task = asyncio.create_task(self._auto_ping())

    async def _auto_ping(self):
        while True:
            await self.proxy.ping_()
            await asyncio.sleep(PING_INTERVAL)

    async def disconnect(self):
        self._listen_task.cancel()
        self._auto_ping_task.cancel()
        await self.ws.close()

    async def listen(self):
        try:
            async for message in self.ws:
                message_object: MessageObject = loads(message)
                asyncio.ensure_future(self._on_message(message_object))
        except websockets.ConnectionClosedError as e:
            print(f"Connection Closed Error in _listen: {e}")
        except Exception as e:
            print(f"Other Exception listen in client: {e}")

    async def _on_message(self, message_object: MessageObject):
        if message_object.error:
            self.tasks.pop(message_object.message_id).set_exception(message_object.result)
        else:
            self.tasks.pop(message_object.message_id).set_result(message_object.result)

    async def _send(self, message_object: MessageObject):
        try:
            future = asyncio.Future()
            self.tasks[message_object.message_id] = future
            await self.ws.send(dumps(message_object))
            return await future
        except websockets.ConnectionClosedError as e:
            print(f"Connection Closed Error in send: {e}")
        except KeyError as e:
            print(f"Key Error in send: {e}")
        except Exception as e:
            print(f"Other Exception in client _send: {e}")


class AsyncIpcServer:
    def __init__(self, klass, ws):
        self.ws = ws
        self.klass = klass

    async def disconnect(self):
        await self.ws.close()

    async def listen(self):
        try:
            async for message in self.ws:
                message_object: MessageObject = loads(message)
                asyncio.ensure_future(self._on_message(message_object))
        except websockets.ConnectionClosedError as e:
            print(f"Connection Closed Error in _listen: {e}")
        except Exception as e:
            print(f"Other Exception in listen server: {e}")

    async def _on_message(self, message_object: MessageObject):
        if message_object.function_name == 'ping_':  # Special function name for auto ping
            message_object.result = True
        else:
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
        await self.ws.send(dumps(message_object))


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

    def __getattr__(self, function_name):
        async def func(*args, **kwargs):
            message_object = MessageObject(function_name, self._next_message_id, *args, *kwargs)
            return await self._send(message_object)
        return func
