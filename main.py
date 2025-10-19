import asyncio
import contextlib
import json
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv, set_key
from textual.app import App
from textual.widgets import Input, Static, Button
from textual.scroll_view import ScrollView
from textual.reactive import reactive
from textual.screen import Screen
from textual.containers import Vertical, Center, Horizontal
from datetime import datetime
from rich.text import Text


DEFAULTS = {
    "USER_NAME": "",
    "DECRYPTION_KEY": "",
    "SERVER_HOST": "",
    "SERVER_PORT": "8000"
}


if not os.path.exists(".env"):
    with open(".env", "w") as f:
        for key, val in DEFAULTS.items():
            f.write(f"{key} = {val}\n")


load_dotenv()
ENV_PATH = ".env"
DEFAULT_USERNAME = os.getenv("USER_NAME", "") or ""
DEFAULT_SERVER_HOST = os.getenv("SERVER_HOST", "") or ""
DEFAULT_SERVER_PORT = int(os.getenv("SERVER_PORT") or 8000)
DEFAULT_DECRYPTION_KEY = os.getenv("DECRYPTION_KEY", "") or ""


class StartScreen(Screen):
    CSS_PATH = "appcss.css"
    def compose(self):
        yield Center(
            Vertical(
                Static("Welcome to Enigma Secure Chat!", classes="banner"),
                Static("\n"+"Enter details or press Start to use .env defaults."),
                Input(placeholder=f"Username (default: {DEFAULT_USERNAME or 'none'})", id="username"),
                Input(placeholder="Encryption key (leave blank to use .env)", id="key"),
                Input(placeholder=f"Server host (default: {DEFAULT_SERVER_HOST})", id="host"),
                Input(placeholder=f"Server port (default: {DEFAULT_SERVER_PORT})", id="port"),
                Center(
                Horizontal(
                    Button("Start Chatting", id="start_button", variant="success"),
                    Button("Start Chatting (Unencrypted)", id="start_button_unencrypted", variant="success"),
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
            
            if not u or not u.strip():
                self.notify("Invalid Username, it cant be empty!", severity="error", timeout=3.0)
                return
            if not (1 <= p <= 65535):
                self.notify("Invalid port number! Must be between 1 and 65535.", severity="error", timeout=3.0)
                return
            if not h or h.isspace() or len(h) > 255:
                self.notify("Invalid server host! Cannot be empty or too long.", severity="error", timeout=3.0)
                return

            current_counter = getattr(self.app, "chat_counter", 0)
            chat_name = f"chat_{current_counter}"
            setattr(self.app, "chat_counter", current_counter + 1)
            self.app.install_screen(ChatScreen(), name=chat_name)
            self.app.push_screen(chat_name)
        
        if event.button.id == "start_button_unencrypted":
            u, k, h, p = self._collect_values()
            self.app.user_config = {
                "username": u,
                "key": k,
                "host": h,
                "port": p,
            }
            setattr(self.app, "encrypted", False)
            if not u or not u.strip():
                self.notify("Invalid Username, it cant be empty!", severity="error", timeout=3.0)
                return
            if not (1 <= p <= 65535):
                self.notify("Invalid port number! Must be between 1 and 65535.", severity="error", timeout=3.0)
                return
            if not h or h.isspace() or len(h) > 255:
                self.notify("Invalid server host! Cannot be empty or too long.", severity="error", timeout=3.0)
                return

            current_counter = getattr(self.app, "chat_counter", 0)
            chat_name = f"chat_{current_counter}"
            setattr(self.app, "chat_counter", current_counter + 1)
            chat_screen = ChatScreen()
            chat_screen.encrypted = False
            self.app.install_screen(chat_screen, name=chat_name)
            self.app.push_screen(chat_name)
            
        
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
        self.readingloop = None
        self.encrypted = True

    def compose(self):
        mode = "Encrypted" if self.encrypted else "Unencrypted"
        status = "Connected" if not self.writer else "Disconnected"
        header = Static(f"{status} to Enigma 4000 in {mode} Mode", classes="header")
        self.message_display = Static("")
        self.activeusers = Static("")
        self.scroll = ScrollView(self.message_display, classes="chat-messages")
        self.active = ScrollView(self.activeusers, classes="active-users")
        self.input_box = Input(placeholder="Type your message and press Enter...")
        self.goback = Button("Disconnect / Go Back to Start", id="goback", variant="success")

        yield Vertical(
            header,
            Horizontal(
                self.scroll,
                self.active,
                classes="chat-layout"
            ),
            Horizontal(
            self.input_box,
            self.goback,
            classes="input-layout"
            )
        )
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
        
        if cfg.get("key") and self.encrypted:
            self.fernet = Fernet(cfg["key"].encode())
            

        self.host = cfg["host"]
        self.port = cfg["port"]

        self.input_box.focus()
        asyncio.create_task(self.tryconnect())
        
    def add_system_message(self, text: str, style: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, "system", text, style))

    def add_user_message(self, username: str, text: str, is_self: bool = False):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, username, text, "self" if is_self else "other"))
        
    async def tryconnect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            handshake = {"username": self.username,
                         "encrypted": self.encrypted
                         }
            self.writer.write((json.dumps(handshake) + "\n").encode())
            await self.writer.drain()
            line = await self.reader.readline()
            if not line:
                raise ConnectionError("No response from server during handshake")
            message = json.loads(line.decode())
            if message.get("system") and "already in use" in message.get("text", "").lower():
                self.messages.append(f"[System] {message['text']}")
                await self.refresh_messages()
                self.writer.close()
                await self.writer.wait_closed()
                self.app.push_screen("start")
                self.app.notify(f"{message['text']}", severity="error", timeout=2.0)
                return
            
            self.messages.append("[Handshake successful]")
            self.readingloop = asyncio.create_task(self.read_loop())
        except Exception as e:
            self.messages.append(f"[Offline mode - no server connection]: {e}")
            await self.refresh_messages()
            self.app.push_screen("start")
            self.app.notify(f"Failed to connect to server {self.host}:{self.port} because of {e}", severity="error", timeout=3.0)
            return
        await self.refresh_messages()

    async def read_loop(self):
        while True:
            try:
                line = await self.reader.readline()
                if not line:
                    self.messages.append("[Disconnected from server]")
                    await self.refresh_messages()
                    if self.writer:
                        self.writer.close()
                        self.readingloop = None
                        await self.writer.wait_closed()
                    self.app.push_screen("start")
                    self.app.notify("Disconnected from server", severity="error", timeout=3.0)
                    return
                message = json.loads(line.decode())

                if message.get("system"):
                    text = message.get("text", "")
                    if "users" in message:
                        self.active_users = message["users"]
                        await self.refresh_active_users()
                    else:
                        self.messages.append(f"[System] {text}")
                        await self.refresh_active_users()
                
                else:
                    payload = message.get("payload", "")
                    if self.encrypted:
                        try:
                            plain_text = self.fernet.decrypt(payload.encode()).decode()
                        except Exception:
                            plain_text = "Decryption failed"
                        timestamp = self.timestamp()
                        self.messages.append((timestamp, message.get('username','Unknown'), plain_text, "other"))
                    else:
                        plain_text = payload
                        timestamp = self.timestamp()
                        self.messages.append((timestamp, message.get('username','Unknown'), plain_text, "other"))

                await self.refresh_messages()
            except Exception as e:
                self.messages.append(f"[Error receiving message: {e}]")
                await self.refresh_messages()


    async def refresh_messages(self):
        lines = []
        for message in self.messages[-40:]:
            if isinstance(message, tuple) and len(message) == 4:
                timestamp, sender, text, style = message
            else:
                timestamp = datetime.now().strftime("%H:%M:%S")
                sender = "system"
                text = str(message)
                style = "info"
            
            line = Text()
            line.append(f"[{timestamp}] ", style="#00ff73")

            if sender == "system":
                line.append("[System] ", style="#001aff")
                if style == "error":
                    line.append("[ERROR] ", style="#ff0000")
                elif style == "success":
                    line.append("[OK] ", style="#00ff73")
            else:
                if style == "self":
                    line.append(f"You: ", style="#eeff00")
                else:
                    line.append(f"{sender}: ", style="#00ffd5")

            line.append(f" {str(text)}", style="#00FF22")
            lines.append(line)

        content = Text("\n").join(lines)
        self.message_display.update(content)
        self.scroll.scroll_end(animate=False)
        
    async def refresh_active_users(self):
        usernumber = str(len(self.active_users))
        userlist = '\n'.join(self.active_users)
        active_users_text = Text(f"Active Users ({usernumber}): \n{userlist}", style="#00eeff")
        self.activeusers.update(active_users_text)
        self.active.scroll_end(animate=False)
        
        
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "goback":
            self.app.push_screen("start")
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



    async def handle_input(self, message: str):
        if not message.strip():
            return
        
        if not self.writer:
            self.add_system_message("❌ Not connected to server", "error")
            await self.refresh_messages()
            return
        if self.encrypted:
            encrypted_message = self.fernet.encrypt(message.encode()).decode()
            data = {"username": self.username, "payload": encrypted_message}
        else:
            data = {"username": self.username, "payload": message}

        try:
            self.writer.write((json.dumps(data) + "\n").encode())
            await self.writer.drain()
            self.add_user_message("You", message, is_self=True)
            await self.refresh_messages()
        except Exception as e:
            self.add_system_message(f"❌ Failed to send: {e}", "error")
            self.writer = None
            self.connected = False
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
        self.chat_counter = 0

    async def on_load(self) -> None:
        self.bind("q", "quit", description="Quit")

    async def on_mount(self) -> None:
        self.install_screen(StartScreen(), name="start")
        self.push_screen("start")
        


if __name__ == "__main__":
    try:
        Client().run()
    finally:
        if os.name != "nt":
            os.system("stty sane")
