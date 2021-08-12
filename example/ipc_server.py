import asyncio
import websockets
from src.ipc import AsyncIpcServer, MAX_SIZE
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
import time


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


async def send_example(client):
    items = 100
    while True:
        jobs = [client.hello() for _ in range(items)]
        t = time.time()
        res = await asyncio.gather(*jobs)
        #print(f"it took {(time.time() - t):.2f} seconds to complete {items} requests.\n"
        #      f"One request took {(time.time() - t) / items * 1000:.4f} millisecond")
        #print(res[0])
        await asyncio.sleep(2)
    print("exited loop")


counter = 0
async def echo(websocket, path):
    global counter
    counter += 1
    print(counter)
    ipc_server = AsyncIpcServer(my_class, websocket)
    #asyncio.ensure_future(send_example(ipc_server.client))
    async def fuck():
        await asyncio.sleep(3)
        await ipc_server.disconnect()
    #asyncio.ensure_future(fuck())
    await ipc_server.listen()
    counter -= 1


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(websockets.serve(echo, 'localhost', 8765, max_size=MAX_SIZE))
    asyncio.get_event_loop().run_forever()
