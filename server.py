import asyncio
import json
import os
import re
import logging
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv


DEFAULTS = {
    "SERVER_HOST": "0.0.0.0",
    "SERVER_PORT": "8000",
    "MAX_USERNAME_LENGTH": "20",
    "RATE_LIMIT": "15"
}

# Create .env file if it doesnt exist

if not os.path.exists(".env"):
    with open(".env", "w") as f:
        for key, val in DEFAULTS.items():
            f.write(f"{key}={val}\n")




load_dotenv()


HOST = os.getenv("SERVER_HOST") or "localhost"
PORT = int(os.getenv("SERVER_PORT") or 8000)
MAX_USERNAME_LENGTH = int(os.getenv("MAX_USERNAME_LENGTH") or 20)
RATE_LIMIT = int(os.getenv("RATE_LIMIT") or 15)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
encrypted_clients = {}
unencrypted_clients = {}
user_message_time = defaultdict(list)


def get_client_group(is_encrypted: bool) -> dict:
    return encrypted_clients if is_encrypted else unencrypted_clients
def validate_username(username: str) -> tuple[bool, str]:
    if not username or not username.strip():
        return False, "Username cannot be empty"
    username = username.strip()
    if len(username) > MAX_USERNAME_LENGTH:
        return False, f"Username too long. Max {MAX_USERNAME_LENGTH} characters"
    if not re.match(r'^[a-zA-Z0-9_\- ]+$', username):
        return False, "Username can only contain alphanumeric characters, underscores, hyphens, and spaces"
    return True, ""
def enforce_rate_limit(username: str) -> bool:
    now = datetime.now().timestamp()
    timestamps = user_message_time[username]
    user_message_time[username] = [t for t in timestamps if now - t < RATE_LIMIT]
    if len(user_message_time[username]) >= RATE_LIMIT:
        return True
    user_message_time[username].append(now)
    return False
async def broadcast(message: dict, exclude=None, encrypted: bool = True):
    group = get_client_group(encrypted)
    line = (json.dumps(message) + "\n").encode()
    for client in list(group.keys()):
        if client != exclude:
            try:
                client.write(line)
                await client.drain()
            except Exception:
                group.pop(client, None)
async def broadcast_current_users_list(encrypted: bool):
    group = get_client_group(encrypted)
    user_list = list(group.values())
    message = {"system": True, "text": "Current Users", "users": user_list}
    await broadcast(message, encrypted=encrypted)
async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    address = writer.get_extra_info("peername")
    username = None
    is_encrypted = True
    logger.info(f"New connection from {address}")
    try:
        while True:
            timeout = 15 if username is None else 300
            try:
                line = await asyncio.wait_for(reader.readline(), timeout)
            except asyncio.TimeoutError:
                logger.info(f"Timeout for {username or address}")
                writer.close()
                await writer.wait_closed()
                return
            if not line:
                return
            try:
                message = json.loads(line.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                if username is None:
                    writer.close()
                    await writer.wait_closed()
                    return
                continue
            if username is None:
                if "username" not in message:
                    writer.close()
                    await writer.wait_closed()
                    return
                username = message["username"].strip()
                is_encrypted = message.get("encrypted", True)
                clients_group = get_client_group(is_encrypted)
                valid, error_msg = validate_username(username)
                if not valid:
                    writer.write((json.dumps({"system": True, "text": error_msg}) + "\n").encode())
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return
                normalized = username.lower()
                if any(u.lower() == normalized for u in clients_group.values()):
                    writer.write((json.dumps({"system": True, "text": "Username already in use"}) + "\n").encode())
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return
                clients_group[writer] = username
                writer.write((json.dumps({"system": True, "text": f"Connected as {username}"}) + "\n").encode())
                await writer.drain()
                logger.info(f"{username} joined from {address}")
                await broadcast({"system": True, "text": f"{username} joined"}, exclude=writer, encrypted=is_encrypted)
                await broadcast_current_users_list(encrypted=is_encrypted)
                continue
            if enforce_rate_limit(username):
                writer.write((json.dumps({"system": True, "text": f"Rate limit exceeded: Max {RATE_LIMIT} messages per {RATE_LIMIT} seconds"}) + "\n").encode())
                await writer.drain()
                continue
            clients_group = get_client_group(is_encrypted)
            await broadcast(message, exclude=writer, encrypted=is_encrypted)

    except Exception as e:
        logger.error(f"Error with client {username or address}: {e}")

    finally:
        clients_group = get_client_group(is_encrypted)
        if writer in clients_group:
            left_user = clients_group.pop(writer)
            logger.info(f"{left_user} disconnected")
            await broadcast({"system": True, "text": f"{left_user} left"}, exclude=writer, encrypted=is_encrypted)
            await broadcast_current_users_list(encrypted=is_encrypted)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def server_stats_logger():
    while True:
        await asyncio.sleep(300)
        logger.info(f"Encrypted clients: {len(encrypted_clients)}, Unencrypted clients: {len(unencrypted_clients)}")


async def main():
    try:
        server = await asyncio.start_server(handle_client, HOST, PORT)
        address = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        logger.info(f"Server started on {address}")
        logging_task = asyncio.create_task(server_stats_logger())
        async with server:
            await server.serve_forever()
    except KeyboardInterrupt:
        print("Server shutting down...")
    finally:
        if 'logging_task' in locals():
            logging_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
