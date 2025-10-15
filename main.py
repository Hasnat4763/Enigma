import asyncio
import json
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from textual.app import App
from textual.widgets import Input
from textual.reactive import Reactive    
load_dotenv()

username = os.getenv("USER_NAME")
server_host = os.getenv("SERVER_HOST")
server_port = os.getenv("SERVER_PORT")
server_port = int(server_port) if server_port else 8000
decryption_key = os.getenv("DECRYPTION_KEY")
if decryption_key:
    fernet = Fernet(decryption_key)
else:
    raise ValueError("Decryption key not found in environment variables.")