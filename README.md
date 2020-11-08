# pyipc
A fast, robust and stable asynchronous inter process communication over websockets api

Usage
-----

IPC methods can be used as ``ipc.proxy.method(*args, **kwarg)``.

Server
~~~~~~

The following code implements a simple IPC server that serves MyClass as endpoint

.. code-block:: python


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
    
    
      from aiohttp.web import Application, run_app
      from aiohttp_json_rpc import JsonRpc
      import asyncio
    
    
      async def ping(request):
          return 'pong'
    
    
      if __name__ == '__main__':
          loop = asyncio.get_event_loop()
    
          rpc = JsonRpc()
          rpc.add_methods(
              ('', ping),
          )
    
          app = Application(loop=loop)
          app.router.add_route('*', '/', rpc.handle_request)
    
          run_app(app, host='0.0.0.0', port=8080)

~~~~~
Client
~~~~~~

The following code implements a simple IPC client that that connects to server above and calls MyClass's methods

.. code-block:: python

    import asyncio
    from src.ipc import IPC
    import time
    import uvloop  # Optional
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    
    
    async def call(items):
        ipc = IPC('ws://localhost:8765', mode="client")
        await ipc.connect()
        echo = ipc.proxy  # Get class instance proxy
    
        jobs = [echo.echo(1, 2, 3, me="hello", you=3) for _ in range(items)]
        t = time.time()
        res = await asyncio.gather(*jobs)
        print(res[0])
    
        print(f"it took {(time.time() -t):.2f} seconds to complete {items} requests.\n"
              f"One request took {(time.time()-t) / items * 1000:.4f} millisecond")
    
        sum_ = await echo.sum(3.14, 2.7)
        print(sum_)
        print(await echo.async_echo(1, 2, 3, me="hello", you=3))
    
        await ipc.disconnect()
    
    
    asyncio.get_event_loop().run_until_complete(call(10_000))

You can make thousands of async requests between classes as if they are on the same interpreter and avoid
shared objects or other techniques when used on multi processes