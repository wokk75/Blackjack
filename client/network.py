import queue
import socket
import threading
from shared.protocol import (
    ACTION_GAME_MOVE,
    ACTION_LOGIN,
    ACTION_REGISTER,
    ACTION_SIT,
    ENCODING,
    HOST,
    MSG_ERROR,
    PORT,
    decode_messages,
    encode_message,
)


class NetworkClient:
    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.connected = False
        self.incoming_queue: queue.Queue[dict] = queue.Queue()

    def connect(self) -> tuple[bool, str]:
        if self.connected:
            return True, "Już połączono."
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self.connected = True
            threading.Thread(target=self._receive_loop, daemon=True).start()
            return True, "Połączono z serwerem."
        except OSError as exc:
            self.connected = False
            return False, f"Nie można połączyć z serwerem: {exc}"

    def _receive_loop(self) -> None:
        buffer = ""
        try:
            while self.connected and self.sock:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk.decode(ENCODING, errors="replace")
                messages, buffer = decode_messages(buffer)
                for msg in messages:
                    self.incoming_queue.put(msg)
        except OSError:
            pass
        finally:
            self.connected = False
            self.incoming_queue.put({
                "type": MSG_ERROR,
                "message": "Utracono połączenie z serwerem.",
            })

    def send(self, payload: dict) -> bool:
        if not self.connected or not self.sock:
            return False
        try:
            self.sock.sendall(encode_message(payload))
            return True
        except OSError:
            self.connected = False
            return False

    def register(self, username: str, password: str) -> bool:
        return self.send({
            "action": ACTION_REGISTER,
            "username": username,
            "password": password,
        })

    def login(self, username: str, password: str) -> bool:
        return self.send({
            "action": ACTION_LOGIN,
            "username": username,
            "password": password,
        })

    def sit_at_table(self) -> bool:
        return self.send({"action": ACTION_SIT})

    def send_move(self, move: str, amount: float = 0.0) -> bool:
        return self.send({
            "action": ACTION_GAME_MOVE,
            "move": move,
            "amount": amount,
        })

    def close(self) -> None:
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass