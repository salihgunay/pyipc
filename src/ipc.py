import asyncio
from websockets import connect, ConnectionClosedError
from websockets.exceptions import InvalidMessage, ConnectionClosedOK
from websockets.client import WebSocketClientProtocol
from websockets.server import WebSocketServerProtocol
from itertools import count
from pickle import loads, dumps
from typing import Dict, Tuple, Callable
from socket import gethostbyname, gaierror
import sys
import lzma

MAX_MSG_ID = 2 ** 32
MAX_SIZE = 1_000_000_000
RECONNECT_MAX_TIME = 5 * 60  # Try 5 mins apart connecting
IPC_TIMEOUT = 1000  # Interprocess call timeout in seconds
RPC_TIMEOUT = 40  # Remote process call timeout in seconds
MB_MULTIPLIER = 1 / (1024 * 1024)  # This value will multiply with raw upload and download size to change in MB


def is_localhost(host: str):
    return host == '::1' or gethostbyname(host) == '127.0.0.1'


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

    async def listen(self):
        """
        This function behaves same when receiving data but different when acting to exceptions
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
        except ConnectionClosedError:
            # print(f"Connection Closed Error in server _listen. Server: {self.server_name}")
            pass
        except Exception as e:
            if self.am_i_server:  # If server
                print(f"Other Exception in server listen: {e}. Server: {self.server_name}")
                self._call_connection_lost_callback()
            else:
                print(f"Other Exception in client listen: {e}. Client: {self.client_name}")
                if not self._should_resend:
                    self._clear_tasks()
                self._call_connection_lost_callback()
                if self._should_reconnect:
                    asyncio.ensure_future(self._reconnect())

    async def _on_message(self, message_object: MessageObject):
        if message_object.reversed_direction:  # If reversed direction simply set the result
            result: [asyncio.Future, MessageObject] = self._remove_task(message_object.message_id)
            if result:
                if message_object.error:
                    result[0].set_exception(message_object.result)
                else:
                    result[0].set_result(message_object.result)
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
                # print(f"Connection Closed Error in client _send: {e}")
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
        self._should_reconnect = reconnect
        self._should_resend = resend
        self._ssl_context = ssl_context

    @property
    def should_reconnect(self) -> bool:
        return self._should_reconnect

    @should_reconnect.setter
    def should_reconnect(self, should_reconnect: bool):
        self._should_reconnect = should_reconnect

    async def connect(self, should_reconnect: bool = None):
        if isinstance(should_reconnect, bool):
            self._should_reconnect = should_reconnect
        try:
            uri = f'ws{"s" if self._ssl_context else ""}://{self._host}:{self._port}'
            self.ws = await connect(uri, max_size=MAX_SIZE, ssl=self._ssl_context)
            if not self._listen_task:
                self._listen_task = asyncio.create_task(self.listen())
            self._call_connection_made_callback()
        except (ConnectionRefusedError, gaierror, InvalidMessage, ConnectionResetError):
            if self._should_reconnect:
                asyncio.ensure_future(self._reconnect())
        except Exception as e:
            print("connect new error happened. add this to upper except")
            print(e, type(e))
            if self._should_reconnect:
                asyncio.ensure_future(self._reconnect())

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
            print("Canceling\n", message_object)
            task.set_exception(ConnectionNotExist)
        self.tasks.clear()
        self.proxy.reset_count()

    async def _reconnect(self):
        # print(f"Sleeping {self._reconnect_delay} then reconnecting. Client: {self.client_name} - Server: {self.server_name}")
        await asyncio.sleep(self._reconnect_delay)
        await self.disconnect()
        await self.connect()
        if self.connected:
            if self._should_resend:
                await self._resend_tasks()
            else:
                self._clear_tasks()
        self._calculate_reconnect_delay()

    def _calculate_reconnect_delay(self):
        if self.connected:
            self._reconnect_delay = 0
        else:
            self._reconnect_delay = min(5 + self._reconnect_delay * 1.5, RECONNECT_MAX_TIME)

    async def disconnect(self, should_reconnect: bool = None):
        if isinstance(self, AsyncIpcClient):
            if isinstance(should_reconnect, bool):  # This is like force quit connecting
                self._should_reconnect = should_reconnect

            if self._listen_task:
                if not self._listen_task.done():
                    self._listen_task.cancel()
                self._listen_task = None

        if self.ws and self.ws.open:
            await self.ws.close()
            self._call_connection_lost_callback()


class AsyncIpcServer(AsyncIpcBase):
    def __init__(self, klass, ws, connection_lost_callback=None, server_name: str = '', client_name: str = ''):
        super().__init__(klass, ws.remote_address[0], connection_lost_callback=connection_lost_callback,
                         server_name=server_name, client_name=client_name)
        self.ws = ws


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
