import asyncio
from websockets.legacy.client import connect
from websockets.exceptions import InvalidMessage, ConnectionClosedOK, ConnectionClosedError
from websockets.client import WebSocketClientProtocol
from websockets.server import WebSocketServerProtocol
from itertools import count
from pickle import loads, dumps
from typing import Dict, Tuple, Callable
from socket import gaierror
import sys
import lzma

MAX_MSG_ID = 2 ** 32
MAX_SIZE = 1_000_000_000
RECONNECT_MAX_TIME = 30  # Try 30 seconds to reconnect max
IPC_TIMEOUT = 1000  # Interprocess call timeout in seconds
RPC_TIMEOUT = 40  # Remote process call timeout in seconds
MB_MULTIPLIER = 1 / (1024 * 1024)  # This value will multiply with raw upload and download size to change in MB
connect.BACKOFF_MAX = 15


def is_localhost(host: str):
    return host == '::1' or host == '127.0.0.1' or host == 'localhost'


class ConnectionNotExist(Exception):
    pass


class MessageObject:
    def __init__(self, function_name: str, message_id: int, args: Tuple, kwargs: Dict, notify: bool = False,
                 sender: str = '', receiver: str = '', timeout: int = None):
        self._function_name = function_name
        self._message_id = message_id
        self._args = args
        self._kwargs = kwargs
        self._result = None
        self._error = False
        self._sender = sender
        self._receiver = receiver
        self._reversed_direction: bool = False
        self._owner = sender
        self._notify: bool = notify
        self._timeout: int = timeout

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
        self._remove_redundant_data()

    def _remove_redundant_data(self):
        self._args = tuple()
        self._kwargs = dict()

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
    def sender(self) -> str:
        return self._sender

    @property
    def receiver(self) -> str:
        return self._receiver

    @property
    def reversed_direction(self) -> bool:
        return self._reversed_direction

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def notify(self) -> bool:
        return self._notify

    @property
    def timeout(self) -> int:
        return self._timeout

    def __str__(self):
        kwargs = ', ' .join([f'{key}={value}' for key, value in self.kwargs.items()])
        return f'def {self.function_name}{*self.args, kwargs} -> {self.result}:\n\t# Message ID: ' \
               f'{self.owner} - {self.message_id}\n\t# Error: {self.error}\n\t# Sender: {self.sender}\n\t# Receiver: ' \
               f'{self.receiver}\n\t# Reversed direction: {self.reversed_direction}\n\t# Notify: {self.notify}'.replace('\'', '')

    def reverse_direction(self):
        temp = self._sender
        self._sender = self._receiver
        self._receiver = temp
        self._reversed_direction = True


class AsyncIpcBase:
    ws: [WebSocketServerProtocol, WebSocketClientProtocol] = None

    def __init__(self, klass, host: str, connection_lost_callback: Callable = None, connection_made_callback: Callable = None,
                 client_name: str = '', server_name: str = ''):
        self.klass = klass
        self.tasks: [Dict, asyncio.Future] = {}
        self.server_name = server_name
        self.client_name = client_name
        self.proxy = Proxy(self._send, client_name, server_name)
        self._connection_lost_callback = connection_lost_callback
        self._connection_made_callback = connection_made_callback
        self._is_localhost = is_localhost(host)  # Is connection between localhost or remote
        self._timeout = IPC_TIMEOUT if self._is_localhost else RPC_TIMEOUT
        self._upload = 0  # Size in mb
        self._download = 0  # Size in mb

    @property
    def connected(self) -> bool:
        if self.ws:
            return self.ws.open
        return False

    @property
    def timeout(self) -> int:
        return self._timeout

    @property
    def compress(self) -> bool:
        return self._is_localhost

    @property
    def upload(self) -> float:
        return self._upload

    @property
    def download(self) -> float:
        return self._download

    def _add_upload(self, size: int):
        self._upload += size * MB_MULTIPLIER

    def _add_download(self, size: int):
        self._download += size * MB_MULTIPLIER

    def _call_connection_lost_callback(self):
        if asyncio.iscoroutinefunction(self._connection_lost_callback):
            asyncio.ensure_future(self._connection_lost_callback())
        elif callable(self._connection_lost_callback):
            self._connection_lost_callback()

    def _call_connection_made_callback(self):
        if asyncio.iscoroutinefunction(self._connection_made_callback):
            asyncio.ensure_future(self._connection_made_callback())
        elif callable(self._connection_made_callback):
            self._connection_made_callback()

    async def connection_lost(self):
        raise NotImplementedError()

    async def connection_made(self):
        raise NotImplementedError()

    async def listen(self):
        """
        This function listens to new messages until connection closed
        """
        try:
            async for message in self.ws:
                message_object: MessageObject
                if not self._is_localhost:
                    self._add_download(sys.getsizeof(message))
                    message_object = loads(lzma.decompress(message))
                else:
                    message_object = loads(message)
                asyncio.ensure_future(self._on_message(message_object))
        finally:
            asyncio.ensure_future(self.connection_lost())

    async def _on_message(self, message_object: MessageObject):
        if message_object.reversed_direction:  # If reversed direction simply set the result
            result: [asyncio.Future, MessageObject] = self._remove_task(message_object.message_id)
            if result and not result[0].cancelled():
                result[0].set_exception(message_object.result) if message_object.error else result[0].set_result(message_object.result)
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
                message_object.reverse_direction()
            try:
                if not message_object.notify:
                    await self._send(message_object)
            except (ConnectionClosedError, ConnectionClosedOK) as e:
                print(f"server _on_message {e}. Server: {self.server_name}")
                pass  # Connection lost, delete instance and wait for another connection

    async def _send(self, message_object: MessageObject):
        if message_object.reversed_direction:
            if not self._is_localhost:
                message = lzma.compress(dumps(message_object))
            else:
                message = dumps(message_object)
            await self.ws.send(message)
            if not self._is_localhost:
                self._add_upload(sys.getsizeof(message))
            # print(f'Sent bytes: {len(raw_message)}')
        else:
            future = asyncio.Future()
            if not message_object.notify:
                self._add_task(future, message_object)
            try:
                if not self._is_localhost:
                    message = lzma.compress(dumps(message_object))
                else:
                    message = dumps(message_object)
                await self.ws.send(message)
                if not self._is_localhost:
                    self._add_upload(sys.getsizeof(message))
            except (ConnectionClosedError, ConnectionClosedOK):
                print(f"Connection Closed Error in client _send:")
                pass  # if Connection error happens reconnecting with listen
            except KeyError as e:
                print(f"Key Error in client _send: {e}")
            except Exception as e:
                print(f"Other Exception in client _send: {e}")
            if message_object.notify:
                future.cancel()
            else:
                try:
                    # If message object has timeout use it else use standard timeout
                    timeout = message_object.timeout or self._timeout
                    return await asyncio.wait_for(future, timeout=timeout)
                except asyncio.TimeoutError:
                    print("Timeout error happened", message_object)
                    self._remove_task(message_object.message_id)

    def _remove_task(self, task_id: int) -> Tuple[asyncio.Future, MessageObject]:
        if self.tasks.get(task_id):
            return self.tasks.pop(task_id)

    def _add_task(self, task: asyncio.Future, message_object: MessageObject):
        self.tasks[message_object.message_id] = (task, message_object)

    async def disconnect(self):
        """
        If this function called in client and reconnect is active, it will try to reconnect
        so if you want to disconnect completely first deactivate reconnect flag than disconnect
        """
        if self.ws and self.ws.open:
            await self.ws.close(code=1000, reason='User disconnected connection')


class AsyncIpcClient(AsyncIpcBase):
    _listen_task = None
    _reconnect_delay = 0

    def __init__(self, klass, host: str = 'localhost', port: int = 8765, client_name: str = '', server_name: str = '',
                 connection_made_callback=None, connection_lost_callback=None, reconnect: bool = False,
                 resend: bool = False, ssl_context=None):
        super().__init__(klass, host, connection_lost_callback=connection_lost_callback, connection_made_callback=connection_made_callback,
                         client_name=client_name, server_name=server_name)
        self._host = host
        self._port = port
        self.ws = None
        self.reconnect = reconnect
        self.resend = resend
        self._ssl_context = ssl_context
        self._wait_until_connected_future = asyncio.Future()

    async def connect(self):
        """
        This is a blocking call, so ensure future when calling this function
        """
        uri = f'ws{"s" if self._ssl_context else ""}://{self._host}:{self._port}'
        async for ws in connect(uri, max_size=MAX_SIZE, ssl=self._ssl_context):
            try:
                self.ws = ws
                self._wait_until_connected_future.set_result(True)
                asyncio.ensure_future(self.connection_made())
                if self.resend:
                    asyncio.ensure_future(self._resend_tasks())
                await self.listen()
            except (ConnectionRefusedError, gaierror, InvalidMessage, ConnectionResetError, ConnectionAbortedError, TimeoutError,
                    ConnectionClosedError):
                pass
            except Exception as e:
                print("connect new error happened. add this to upper except")
                print(e, type(e))
            finally:
                self._wait_until_connected_future = asyncio.Future()
                if self.reconnect is False:  # exit if reconnect is disabled
                    break

    async def wait_until_connected(self):
        """
        This function blocks until connection made
        """
        if not self.connected:
            return await self._wait_until_connected_future

    async def _resend_tasks(self):
        task: asyncio.Future
        message_object: MessageObject
        print(f"resending {len(self.tasks)} tasks. Client: {self.client_name} - Server: {self.server_name}")
        for task, message_object in self.tasks.values():
            await self.ws.send(dumps(message_object))

    def _clear_tasks(self):
        task: asyncio.Future
        message_object: MessageObject
        for task, message_object in self.tasks.values():
            # print("Canceling\n", message_object)
            task.set_exception(ConnectionNotExist())
        self.tasks.clear()
        self.proxy.reset_count()

    def _calculate_reconnect_delay(self):
        if self.connected:
            self._reconnect_delay = 0
        else:
            self._reconnect_delay = min(1 + self._reconnect_delay * 1.2, RECONNECT_MAX_TIME)

    async def connection_lost(self):
        if not self.resend:
            self._clear_tasks()
        self._call_connection_lost_callback()

    async def connection_made(self):
        if self.resend:
            await self._resend_tasks()
        self._call_connection_made_callback()


class AsyncIpcServer(AsyncIpcBase):
    def __init__(self, klass, ws, connection_lost_callback=None, server_name: str = '', client_name: str = ''):
        super().__init__(klass, ws.remote_address[0], connection_lost_callback=connection_lost_callback,
                         server_name=server_name, client_name=client_name)
        self.ws = ws

    async def connection_lost(self):
        self._call_connection_lost_callback()

    async def connection_made(self):
        self._call_connection_made_callback()


class Proxy:
    def __init__(self, send: Callable, sender: str = '', receiver: str = ''):
        self._send = send
        self._iter = count()
        self._sender = sender
        self._receiver = receiver

    @property
    def _next_message_id(self) -> int:
        message_id = next(self._iter)
        if message_id > MAX_MSG_ID:
            self.reset_count()
        return message_id

    def __getattr__(self, function_name):
        async def func(*args, **kwargs):
            notify = False
            if kwargs.get('notify'):
                notify = kwargs.pop('notify')

            timeout = None
            if kwargs.get('timeout'):
                timeout = kwargs.pop('timeout')

            message_object = MessageObject(function_name=function_name, message_id=self._next_message_id, notify=notify,
                                           sender=self._sender, receiver=self._receiver, timeout=timeout, args=args,
                                           kwargs=kwargs)
            return await self._send(message_object)
        return func

    def reset_count(self):
        self._iter = count()
