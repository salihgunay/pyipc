import asyncio
import random

from src.ipc import AsyncIpcClient
import uvloop  # Optional
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


class ClientClass:
    server_class = None

    async def multiply(self, a: float, b: float) -> float:
        return a*b

    async def connect(self):
        ipc_client = AsyncIpcClient(self)
        await ipc_client.connect()
        self.server_class = ipc_client.proxy  # Get class instance proxy
        for i in range(2000):
            jobs = [self.server_class.sum(random.random(), i / 2) for i in range(10_000)]
            res = await asyncio.gather(*jobs)
            print(res)

        # This will not be here, event loop will take care of run forever
        await asyncio.sleep(100)

    @staticmethod
    def reverse_echo_from_server(sentence: str) -> str:
        return sentence


async def call():
    client = ClientClass()
    await client.connect()

try:
    asyncio.get_event_loop().run_until_complete(call())
except KeyboardInterrupt:
    print("Keyboard interrupt")

