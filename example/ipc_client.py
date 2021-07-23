import asyncio
from src.ipc import AsyncIpcClient
import time
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

max_sleep_time = 2 ** 32
import random


async def call_later(jobs):
    await asyncio.sleep(random.random() * 10)
    await asyncio.gather(*jobs)


async def call():
    ipc = AsyncIpcClient()
    await ipc.connect()
    my_class = ipc.proxy  # Get class instance proxy
    while True:
        jobs = [my_class.echo("hello world!") for _ in range(100)]
        random_jobs = [my_class.echo("hello world!") for _ in range(250)]
        asyncio.ensure_future(call_later(random_jobs))
        res = await asyncio.gather(*jobs)
        print("finished", res)
        await asyncio.sleep(10)

    await ipc.disconnect()

try:
    asyncio.get_event_loop().run_until_complete(call())
except KeyboardInterrupt:
    print("Keyboard interrupt")

