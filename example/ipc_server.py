import asyncio
import websockets
from src.ipc import AsyncIpcServer, MAX_SIZE
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


class ServerClass:
    _secret_value = "My Secret"

    @staticmethod
    def echo(sentence: str):
        return sentence

    @staticmethod
    async def async_echo(sentence: str):
        await asyncio.sleep(.5)
        return sentence

    @staticmethod
    def sum(a: float, b: float, **kwargs) -> float:
        return a + b

    def get_secret_value(self) -> str:
        return self._secret_value


server_class = ServerClass()


async def echo(websocket, _):
    ipc_server = AsyncIpcServer(server_class, websocket)
    task = asyncio.create_task(ipc_server.listen())
    for i in range(2500):
        print(await ipc_server.proxy.multiply(i, i/2))
    await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(websockets.serve(echo, 'localhost', 8765, max_size=MAX_SIZE))
    asyncio.get_event_loop().run_forever()
