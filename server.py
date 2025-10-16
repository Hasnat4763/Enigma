import asyncio
import json
import os
from dotenv import load_dotenv



load_dotenv()

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 8000))

clients = set()

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    address = writer.get_extra_info('peername')
    username = None
    clients.add(writer)
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
                username = message["username"]
                print(f"{username} joined from {address}")
            
            
            for client in clients:
                if client != writer:
                    client.write(line)
                    await client.drain()
    except asyncio.CancelledError:
        pass
    
    finally:
        clients.remove(writer)
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