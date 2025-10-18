import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 8000))

clients = {}

async def broadcast(message: dict, exclude=None):
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
            if username is None:
                timeout = 15
            else:
                timeout = 300
            
            try:
                line = await asyncio.wait_for(reader.readline(), timeout)
            except asyncio.TimeoutError:
                if username is None:
                    print(f"Handshake timeout from {address}")
                else:
                    print(f"Idle timeout for {username}")
                writer.close()
                await writer.wait_closed()
                return
            
            if not line:
                return

            try:
                message = json.loads(line.decode())
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"Error decoding message from {username or address}: {e}")
                if username is None:
                    writer.close()
                    await writer.wait_closed()
                    return
                continue

            if username is None:
                if "username" not in message:
                    print(f"No username in handshake from {address}")
                    writer.close()
                    await writer.wait_closed()
                    return
                
                requested = message["username"]

                if requested in clients.values():
                    error = {"system": True, "text": "already in use"}
                    print(f"Username {requested} already in use from {address}")
                    writer.write((json.dumps(error) + "\n").encode())
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return
            
                username = requested
                clients[writer] = username
                welcome = {"system": True, "text": f"Connected as {username}"}
                writer.write((json.dumps(welcome) + "\n").encode())
                await writer.drain()
                
                print(f"{username} joined from {address}")
                await broadcast({"system": True, "text": f"{username} joined"}, exclude=writer)
                continue
            await broadcast(message, exclude=writer)

    finally:
        if writer in clients:
            left_user = clients.pop(writer, None) or str(address)
            print(f"{left_user} disconnected")
            await broadcast({"system": True, "text": f"{left_user} left"}, exclude=writer)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    try:
        server = await asyncio.start_server(handle_client, HOST, PORT)
        address = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        print(f"Serving on {address}")
        async with server:
            await server.serve_forever()
    except KeyboardInterrupt:
        print("Server shutting down...")
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
