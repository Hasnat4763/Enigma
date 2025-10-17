import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 8000))

clients = {}

async def broadcast(message: dict, exclude=None):
    """Send a JSON message to all connected clients except `exclude`."""
    line = (json.dumps(message) + "\n").encode()
    for client in list(clients.keys()):
        if client != exclude:
            try:
                client.write(line)
                await client.drain()
            except Exception:
                clients.pop(client, None)
async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    address = writer.get_extra_info("peername")
    username = None
    print(f"New connection from {address}")

    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                message = json.loads(line.decode())
            except Exception:
                continue
            if username is None and "username" in message:
                requested = message["username"]
                if requested in clients.values():
                    error = {"system": True, "text": "already in use"}
                    writer.write((json.dumps(error) + "\n").encode())
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return
                username = requested
                clients[writer] = username
                print(f"{username} joined from {address}")
                await broadcast({"system": True, "text": f"{username} joined"}, exclude=writer)
                continue
            await broadcast(message, exclude=writer)

    finally:
        if writer in clients:
            left_user = clients.pop(writer, None) or str(address)
            print(f"{left_user} disconnected")
            await broadcast({"system": True, "text": f"{left_user} left"}, exclude=writer)
        writer.close()
        await writer.wait_closed()


async def main():
    server = await asyncio.start_server(handle_client, HOST, PORT)
    address = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    print(f"Serving on {address}")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())