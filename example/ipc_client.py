import asyncio
from src.ipc import AsyncIpcClient
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


async def call():
    ipc = AsyncIpcClient()
    await ipc.connect()
    server_class = ipc.proxy  # Get class instance proxy
    res = await server_class.echo("Hello World!")
    print(res)
    res = await server_class.sum(3, 5)
    print(res)

    await ipc.disconnect()


try:
    asyncio.get_event_loop().run_until_complete(call())
except KeyboardInterrupt:
    print("Keyboard interrupt")

