# pyipc
A fast, robust and stable asynchronous inter process communication over websockets api

Usage
-----

IPC methods can be used as ``ipc.proxy.method(*args, **kwarg)``.


#### Server


The following code implements a simple IPC server that serves MyClass as endpoint

```python
import asyncio
import websockets
from src.ipc import IPC
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
   
    
class MyClass:

    def echo(self, *args, **kwargs):
        return args, kwargs

    async def async_echo(self, *args, **kwargs):
        await asyncio.sleep(.5)
        return args, kwargs

    @staticmethod
    def sum(a: float, b: float) -> float:
        return a + b


async def echo(websocket, path):
    ipc_server = IPC(ws=websocket, cls=MyClass(), mode="server")
    await ipc_server.listen()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(websockets.serve(echo, 'localhost', 8765, max_size=1_000_000_000))
    asyncio.get_event_loop().run_forever()
```


#### Client
The following code implements a simple IPC client that that connects to server above and calls MyClass' methods

```python
import asyncio
from src.ipc import IPC
import time
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


async def call(items):
    ipc = IPC('ws://localhost:8765', mode="client")
    await ipc.connect()
    my_class = ipc.proxy  # Get class instance proxy

    jobs = [my_class.echo(1, 2, 3, me="hello", you=3) for _ in range(items)]
    t = time.time()
    res = await asyncio.gather(*jobs)
    print(res[0])

    print(f"it took {(time.time() -t):.2f} seconds to complete {items} requests.\n"
          f"One request took {(time.time()-t) / items * 1000:.4f} millisecond")

    sum_ = await my_class.sum(3.14, 2.7)
    print(sum_)
    print(await my_class.async_echo(1, 2, 3, me="hello", you=3))

    await ipc.disconnect()


asyncio.get_event_loop().run_until_complete(call(10_000))
```

You can make thousands of async requests between classes as if they are on the same interpreter and avoid
shared objects or other techniques complexity when used on multi processes