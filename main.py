import asyncio
import contextlib
import json
import os
import logging
from cryptography.fernet import Fernet
from dotenv import load_dotenv, set_key
from textual.app import App
from textual.widgets import Input, Static, Button
from textual.scroll_view import ScrollView
from textual.reactive import reactive
from textual.screen import Screen
from textual.containers import Vertical, Center, Horizontal
from datetime import datetime

logging.getLogger("textual").setLevel(logging.CRITICAL)

load_dotenv()
ENV_PATH = ".env"
DEFAULT_USERNAME = os.getenv("USER_NAME", "") or ""
DEFAULT_SERVER_HOST = os.getenv("SERVER_HOST", "") or "127.0.0.1"
DEFAULT_SERVER_PORT = int(os.getenv("SERVER_PORT") or 8000)
DEFAULT_DECRYPTION_KEY = os.getenv("DECRYPTION_KEY", "") or ""

class StartScreen(Screen):
    CSS_PATH = "appcss.css"
    def compose(self):
        yield Center(
            Vertical(
                Static("🕵️ Welcome to Enigma Secure Chat!", classes="banner"),
                Static("\n"+"Enter details or press Start to use .env defaults."),
                Input(placeholder=f"Username (default: {DEFAULT_USERNAME or 'none'})", id="username"),
                Input(placeholder="Encryption key (leave blank to use .env)", id="key"),
                Input(placeholder=f"Server host (default: {DEFAULT_SERVER_HOST})", id="host"),
                Input(placeholder=f"Server port (default: {DEFAULT_SERVER_PORT})", id="port"),
                Center(
                Horizontal(
                    Button("Start Chatting", id="start_button", variant="success"),
                    Button("Generate Key", id="generate_key_button", variant="primary"),
                    Button("Save as default (.env)", id="save_button", variant="primary"),
                    Button("Quit", id="quit_button", variant="primary"),
                    classes="button-row",
                ),
                ),
            classes="start-box",
            ),
            id="dialog"
            
            
        )

    def _collect_values(self):
        u = self.query_one("#username", Input).value.strip() or DEFAULT_USERNAME
        k = self.query_one("#key", Input).value.strip() or DEFAULT_DECRYPTION_KEY
        h = self.query_one("#host", Input).value.strip() or DEFAULT_SERVER_HOST
        p_text = self.query_one("#port", Input).value.strip() or str(DEFAULT_SERVER_PORT)
        try:
            p = int(p_text)
        except ValueError:
            p = DEFAULT_SERVER_PORT
        return u, k, h, p

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save_button":
            u, k, h, p = self._collect_values()
            set_key(ENV_PATH, "USER_NAME", u)
            set_key(ENV_PATH, "DECRYPTION_KEY", k)
            set_key(ENV_PATH, "SERVER_HOST", h)
            set_key(ENV_PATH, "SERVER_PORT", str(p))
            self.notify("Saved to .env", severity="information", timeout=2.0)
            return
        if event.button.id == "generate_key_button":
            newkey = Fernet.generate_key().decode()
            self.query_one("#key", Input).value = newkey
            self.notify("New key generated! Save it to .env to keep it.", severity="information", timeout=3.0)
            return
        if event.button.id == "start_button":
            u, k, h, p = self._collect_values()
            self.app.user_config = {
                "username": u,
                "key": k,
                "host": h,
                "port": p,
            }
            try:
                Fernet(k.encode())
            except Exception:
                self.notify("Invalid encryption key! Check format and length.", severity="error", timeout=3.0)
                return
            if not (1 <= p <= 65535):
                self.notify("Invalid port number! Must be between 1 and 65535.", severity="error", timeout=3.0)
                return
            if not h or h.isspace() or len(h) > 255:
                self.notify("Invalid server host! Cannot be empty or too long.", severity="error", timeout=3.0)
                return
            self.app.push_screen("chat")
        
        if event.button.id == "quit_button":
            self.app.exit()
            
            
class ChatScreen(Screen):
    CSS_PATH = "appcss.css"
    messages = reactive(list)

    def __init__(self):
        super().__init__()
        self.reader = None
        self.writer = None
        self.username = None
        self.fernet = None
        self.host = None
        self.port = None

    def compose(self):
        self.message_display = Static("Enigma")
        self.scroll = ScrollView(self.message_display)
        self.input_box = Input(placeholder="Type your message and press Enter...")
        yield self.scroll
        yield self.input_box

    async def on_mount(self) -> None:
        cfg = getattr(self.app, "user_config", None)
        if not cfg:
            cfg = {
                "username": DEFAULT_USERNAME,
                "key": DEFAULT_DECRYPTION_KEY,
                "host": DEFAULT_SERVER_HOST,
                "port": DEFAULT_SERVER_PORT,
            }

        self.username = cfg["username"]
        self.fernet = Fernet(cfg["key"])
        self.host = cfg["host"]
        self.port = cfg["port"]

        self.input_box.focus()
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.messages.append("[Connected to server]")
            join_message = {"system": True, "text": f"{self.username} has joined the chat"}
            self.writer.write((json.dumps(join_message) + "\n").encode())
            await self.writer.drain()

            self.readingloop = asyncio.create_task(self.read_loop())
        except Exception:
            self.messages.append("[Offline mode - no server connection]")
        await self.refresh_messages()

    async def read_loop(self):
        while True:
            try:
                if not self.reader:
                    await asyncio.sleep(0.25)
                    continue
                line = await self.reader.readline()
                if not line:
                    continue
                message = json.loads(line.decode())
                if message.get("system"):
                    self.messages.append(f"[{self.timestamp()}] [System] {message.get('text','')}")
                else:
                    payload = message.get("payload", "")
                    try:
                        plain_text = self.fernet.decrypt(payload.encode()).decode()
                    except Exception:
                        plain_text = "[Decryption failed]"
                    self.messages.append(f"[{self.timestamp()}] {message.get('username','Unknown')}: {plain_text}")
                await self.refresh_messages()
            except Exception as e:
                self.messages.append(f"[Error receiving message: {e}]")
                await self.refresh_messages()

    async def refresh_messages(self):
        content = "\n".join(self.messages[-20:])
        self.message_display.update(content)
        self.scroll.scroll_end(animate=False)

    async def handle_input(self, message: str):
        if not message.strip():
            return
        encrypted_message = self.fernet.encrypt(message.encode()).decode()
        data = {"username": self.username, "payload": encrypted_message}
        if self.writer:
            self.writer.write((json.dumps(data) + "\n").encode())
            await self.writer.drain()
        else:
            self.messages.append("[Offline mode - no server connection]")
        self.messages.append(f"You: {message}")
        await self.refresh_messages()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        await self.handle_input(event.value)
        self.input_box.value = ""

    async def on_unmount(self) -> None:
        if self.readingloop:
            self.readingloop.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.readingloop
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass

    
    def timestamp(self):
        return datetime.now().strftime("%H:%M:%S")



class Client(App):
    def __init__(self):
        super().__init__()
        self.user_config = None

    async def on_load(self) -> None:
        self.bind("q", "quit", description="Quit")

    async def on_mount(self) -> None:
        self.install_screen(StartScreen(), name="start")
        self.install_screen(ChatScreen(), name="chat")
        self.push_screen("start")


if __name__ == "__main__":
    try:
        Client().run()
    finally:
        os.system("stty sane")
