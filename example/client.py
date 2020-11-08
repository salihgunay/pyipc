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


