import asyncio
from src.ipc import AsyncIpcClient
import time
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

max_sleep_time = 2 ** 32
import random


async def call_later(jobs):
    await asyncio.sleep(random.random() * 3)
    res = await asyncio.gather(*jobs)
    #print("other res", res)


async def call():
    ipc = AsyncIpcClient()
    await ipc.connect()
    my_class = ipc.proxy  # Get class instance proxy
    items = 20_000
    while True:
        jobs = [my_class.echo(1, 2, 3, me="hello", you=3) for _ in range(items)]
        t = time.time()
        res = await asyncio.gather(*jobs)
        print(f"it took {(time.time() -t):.2f} seconds to complete {items} requests.\n"
              f"One request took {(time.time()-t) / items * 1000:.4f} millisecond")
        print(res[0])



    await ipc.disconnect()

try:
    asyncio.get_event_loop().run_until_complete(call())
except KeyboardInterrupt:
    print("Keyboard interrupt")

