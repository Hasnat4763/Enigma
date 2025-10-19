import asyncio
import json
import os
import re
import logging
from collections import defaultdict
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 8000))
MAX_USERNAME_LENGTH = 20
RATE_LIMIT = 15


logging.basicConfig(
    level = logging.INFO,
    format = "%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("server.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

clients = {}

user_message_time = defaultdict(list)

def validate_username(username: str) -> tuple[bool, str]:
    if not username or not username.strip():
        return False, "Username Cant Be Empty"
    
    username = username.strip()
    
    if len(username) > MAX_USERNAME_LENGTH:
        return False, f"Username Too Long Max {MAX_USERNAME_LENGTH} Characters"
    
    if not re.match(r'^[a-zA-Z0-9_\- ]+$', username):
        return False, "Username Can Only Contain Alphanumeric Characters And Underscores"

    return True, ""

def enforce_rate_limit(username: str) -> bool:
    now = datetime.now().timestamp()
    timestamps = user_message_time[username]
    
    user_message_time[username] = [t for t in timestamps if now - t < RATE_LIMIT]
    
    if len(user_message_time[username]) >= RATE_LIMIT:
        return True
    
    user_message_time[username].append(now)
    return False

async def broadcast_current_users_list():
    user_list = list(clients.values())
    message = {
        "system": True,
        "text": "Current Users",
        "users": user_list
    }
    await broadcast(message)

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
    logger.info(f"New connection from {address}")

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
                is_valid, error_msg = validate_username(requested)
                if not is_valid:
                    error = {"system": True, "text": error_msg}
                    print(f"Invalid username {requested} from {address}: {error_msg}")
                    writer.write((json.dumps(error) + "\n").encode())
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return
                    
                normalized = requested.strip().lower()
                if any(u.strip().lower() == normalized for u in clients.values()):
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
                await broadcast_current_users_list()
                continue
            
            if enforce_rate_limit(username):
                error = {"system": True, "text": f"Rate Limit Exceeded: Max {RATE_LIMIT} messages per {RATE_LIMIT} seconds"}
                writer.write((json.dumps(error) + "\n").encode())
                await writer.drain()
                continue
            await broadcast(message, exclude=writer)
                
    except Exception as e:
        logger.error(f"Error with client {username or address}: {e}")
                    
            

    finally:
        if writer in clients:
            left_user = clients.pop(writer, None) or str(address)
            logger.info(f"{left_user} disconnected")
            await broadcast({"system": True, "text": f"{left_user} left"}, exclude=writer)
            await broadcast_current_users_list()
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def server_stats_logger():
    while True:
        await asyncio.sleep(300)
        logger.info(f"Server Stats: Connected Clients: {len(clients)}, Users: {list(clients.values())}")




async def main():
    try:
        server = await asyncio.start_server(handle_client, HOST, PORT)
        address = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        logger.info(f"Server Started on {address}")
        logger.info("Configuration:")
        logger.info(f"Max Username Length: {MAX_USERNAME_LENGTH}")
        logger.info(f"Rate Limit: {RATE_LIMIT} messages per {RATE_LIMIT} seconds")
        
        logging_task = asyncio.create_task(server_stats_logger())
        
        print(f"Serving on {address}")
        async with server:
            await server.serve_forever()
    except KeyboardInterrupt:
        print("Server shutting down...")
    except Exception as e:
        print(f"Server error: {e}")
        
    finally:
        if 'logging_task' in locals():
            try:
                logging_task.cancel()
            except Exception as e:
                logger.error(f"Error cancelling logging task: {e}")


if __name__ == "__main__":
    asyncio.run(main())