import asyncio
import websockets
from src.ipc import AsyncIpcServer, MAX_SIZE
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


class MyClass:
    _secret_value = "My Secret"

    @staticmethod
    def echo(sentence: str):
        return sentence

    @staticmethod
    async def async_echo(sentence: str):
        await asyncio.sleep(.5)
        return sentence

    @staticmethod
    def sum(a: float, b: float) -> float:
        return a + b

    def get_secret_value(self) -> str:
        return self._secret_value



my_class = MyClass()


async def echo(websocket, _):
    ipc_server = AsyncIpcServer(my_class, websocket)
    await ipc_server.listen()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(websockets.serve(echo, 'localhost', 8765, max_size=MAX_SIZE))
    asyncio.get_event_loop().run_forever()
