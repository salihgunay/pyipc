import asyncio
import websockets
from src.ipc import AsyncIpcServer, MAX_SIZE
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

my_class = MyClass()

async def echo(websocket, path):
    ipc_server = AsyncIpcServer(my_class, websocket)
    await ipc_server.listen()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(websockets.serve(echo, 'localhost', 8765, max_size=MAX_SIZE))
    asyncio.get_event_loop().run_forever()
