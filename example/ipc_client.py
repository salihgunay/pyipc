import asyncio
from src.ipc import AsyncIpcClient
import time
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

max_sleep_time = 2 ** 32
import random


class Hello:
    async def hello(self):
        #print("I am called men")
        return "f you"


async def call():
    ipc = AsyncIpcClient(klass=Hello(), resending=False)
    await ipc.connect()
    my_class = ipc.server  # Get class instance proxy
    items = 10_000
    while True:
        try:
            jobs = [my_class.echo(1, 2, 3, me="hello", you=3) for _ in range(items)]
            t = time.time()
            res = await asyncio.gather(*jobs)
        except Exception as e:
            print(e)
        #print(f"it took {(time.time() -t):.2f} seconds to complete {items} requests.\n"
        #      f"One request took {(time.time()-t) / items * 1000:.4f} millisecond")
        #print(res[0])
        #await asyncio.sleep(8)

    await ipc.disconnect()


async def call_2():
    ipc = AsyncIpcClient(klass=Hello(), resending=False)
    await ipc.connect()
    my_class = ipc.server  # Get class instance proxy
    items = 1
    while True:
        try:
            jobs = [my_class.echo(1, 2, 3, me="hello", you=3) for _ in range(items)]
            t = time.time()
            res = await asyncio.gather(*jobs)
        except Exception as e:
            print(e)
        #print(f"it took {(time.time() -t):.2f} seconds to complete {items} requests.\n"
        #      f"One request took {(time.time()-t) / items * 1000:.4f} millisecond")
        #print(res[0])
        await asyncio.sleep(8)

    await ipc.disconnect()

try:
    jobs = [call_2() for _ in range(100)]
    asyncio.get_event_loop().run_until_complete(asyncio.gather(*jobs))
except KeyboardInterrupt:
    print("Keyboard interrupt")

