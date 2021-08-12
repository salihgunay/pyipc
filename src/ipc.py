import asyncio
import websockets
from itertools import count
from pickle import loads, dumps
from typing import Dict, Tuple

MAX_MSG_ID = 2 ** 32
MAX_SIZE = 1_000_000_000
PING_INTERVAL = 10


class MessageObject:
    def __init__(self, function_name_: str, message_id_: int, *args, is_client_calling_: bool = True, **kwargs):
        self._function_name = function_name_
        self._message_id = message_id_
        self._args = args
        self._kwargs = kwargs
        self._result = None
        self._error = False
        self._is_client_calling = is_client_calling_

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

    @property
    def is_client_calling(self):
        return self._is_client_calling


class IpcBase:
    def __init__(self, klass=None, ws=None):
        self.klass = klass
        self.tasks: [Dict, asyncio.Future] = {}
        self.ws = ws
        if not (isinstance(self, AsyncIpcClient) or isinstance(self, AsyncIpcServer)):
            raise Exception('Ipc Client or Ipc Server expected')

        self._am_i_ipc_client = isinstance(self, AsyncIpcClient)

    @property
    def connected(self) -> bool:
        if self.ws:
            return self.ws.open
        return False

    @property
    def name(self) -> str:
        return 'client' if self._am_i_ipc_client else 'server'

    async def listen(self):
        try:
            async for message in self.ws:
                message_object: MessageObject = loads(message)
                asyncio.ensure_future(self._on_message(message_object))
        except websockets.ConnectionClosedError as e:
            print(f"Connection Closed Error in {self.name} _listen: {e}, {self.connected}")
        except Exception as e:
            print(f"Other Exception in {self.name} _listen: {e}")

    async def _on_message(self, message_object: MessageObject):
        if (message_object.is_client_calling and self._am_i_ipc_client) or \
                (not message_object.is_client_calling and not self._am_i_ipc_client):
            future, message_object_ = self.tasks.pop(message_object.message_id)
            if future.done():
                return

            if message_object.error:
                future.set_exception(message_object.result)
            else:
                future.set_result(message_object.result)
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
            try:
                if self.connected:
                    await self.ws.send(dumps(message_object))
            except (websockets.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK) as e:
                print(f"{self.name} _on_message {e}")
                pass  # Connection lost, delete instance and wait for another connection

    async def _send(self, message_object: MessageObject):
        future = asyncio.Future()
        try:
            self.tasks[message_object.message_id] = (future, message_object)
            if self.connected:
                await self.ws.send(dumps(message_object))
        except (websockets.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK) as e:
            # print(f"Connection Closed Error in client _send: {e}")
            pass  # if Connection error happens reconnecting with listen
        except KeyError as e:
            print(f"Key Error in {self.name} _send: {e}")
        except Exception as e:
            print(f"Other Exception in {self.name} _send: {e}")
        return await future


class AsyncIpcClient(IpcBase):

    def __init__(self, host: str = 'localhost', port: int = 8765, resending: bool = True, klass=None,
                 connection_lost_callback=None):
        super().__init__(klass=klass)
        self._host = host
        self._port = port
        self.server = Proxy(self._send, is_client_proxy=True)
        self._connection_lost_callback = connection_lost_callback
        self._listen_task = None
        self._resending = resending  # Should client try to resend tasks

    async def connect(self):
        self.ws = await websockets.connect(f'ws://{self._host}:{self._port}', max_size=MAX_SIZE, ping_interval=None)
        if not self._listen_task:
            self._listen_task = asyncio.create_task(self.listen())

    async def _resend_tasks(self):
        task: asyncio.Future
        message_object: MessageObject
        print(f"resending {len(self.tasks)} tasks.")
        for task, message_object in self.tasks.values():
            await self.ws.send(dumps(message_object))

    def _cancel_tasks(self):
        task: asyncio.Future
        message_object: MessageObject
        print(f"canceling {len(self.tasks)} tasks.")
        exception = Exception("Tasks cancelled because connection closed")
        for task, message_object in self.tasks.values():
            task.set_exception(exception)
        self.tasks = {}

    async def _reconnect(self):
        print(f"reconnecting.")
        await self.disconnect()
        # First of all cancel all tasks and clear list
        if not self._resending:
            self._cancel_tasks()
        await self.connect()
        if self._resending:
            await self._resend_tasks()
        else:
            self._cancel_tasks()

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
        await super().listen()
        asyncio.ensure_future(self._reconnect())


class AsyncIpcServer(IpcBase):

    def __init__(self, klass, ws):
        super().__init__(klass=klass, ws=ws)
        self.client = Proxy(self._send, is_client_proxy=False)

    async def disconnect(self):
        await self.ws.close()


class Proxy:
    def __init__(self, send, is_client_proxy: bool = True):
        self._send = send
        self._iter = count()
        self._is_client_proxy = is_client_proxy

    @property
    def _next_message_id(self) -> int:
        message_id = next(self._iter)
        if message_id > MAX_MSG_ID:
            self._iter = count()
        return message_id

    def __getattr__(self, function_name_):
        async def func(*args, **kwargs):
            message_object = MessageObject(function_name_, self._next_message_id, *args,
                                           is_client_calling_=self._is_client_proxy, **kwargs)
            return await self._send(message_object)
        return func
