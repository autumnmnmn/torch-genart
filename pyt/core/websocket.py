
import asyncio
import json
import queue
import threading

HOST = "0.0.0.0"
PORT = 1314

class WebsocketServer:
    def __init__(self, log):
        self.log = log
        self._send = queue.Queue()
        self._received = queue.Queue()
        self.clients = set()
        self.connected = False

        try:
            import websockets
            self._websockets = websockets
        except ImportError:
            self.log("websockets package not available; webui server disabled", mode="info")
            return

        threading.Thread(target=self._run, daemon=True, name="pyt-webui").start()

    def send(self, item):
        self._send.put(item)

    def receive(self, block=True, timeout=None):
        return self._received.get(block, timeout)

    def _run(self):
        try:
            asyncio.run(self._serve())
        except OSError:
            self.log(f"port {PORT} unavailable; webui server disabled", mode="info")
        except Exception:
            self.log.trace()

    async def _handler(self, websocket):
        self.clients.add(websocket)
        try:
            async for message in websocket:
                self._received.put(message)
        finally:
            self.clients.discard(websocket)

    async def _pump(self):
        while True:
            item = await asyncio.to_thread(self._send.get)
            if isinstance(item, (dict, list)):
                item = json.dumps(item, default=str)
            if self.clients:
                await asyncio.gather(
                    *(client.send(item) for client in list(self.clients)),
                    return_exceptions=True)

    async def _serve(self):
        async with self._websockets.serve(self._handler, HOST, PORT):
            self.connected = True
            self.log(f"socket server @ {HOST}:{PORT}")
            await self._pump()

