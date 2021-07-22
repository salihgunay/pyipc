import asyncio
from src.ipc import AsyncIpcClient
import time
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


async def call(items):
    ipc = AsyncIpcClient()
    await ipc.connect()
    my_class = ipc.proxy  # Get class instance proxy

    jobs = [my_class.echo() for _ in range(items)]
    t = time.time()
    await asyncio.gather(*jobs)

    print(f"it took {(time.time() -t):.2f} seconds to complete {items} requests.\n"
          f"One request took {(time.time()-t) / items * 1000:.4f} millisecond")

    await ipc.disconnect()


asyncio.get_event_loop().run_until_complete(call(100_000))


