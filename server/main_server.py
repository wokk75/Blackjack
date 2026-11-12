import socket
import threading
import time
from server.database import DatabaseManager
from server.game_engine import BlackjackTable
from shared.protocol import (
    ACTION_GAME_MOVE,
    ACTION_LOGIN,
    ACTION_REGISTER,
    ACTION_SIT,
    ENCODING,
    HOST,
    MSG_AUTH_RESULT,
    MSG_ERROR,
    MSG_STATE_UPDATE,
    PHASE_WAITING,
    PORT,
    decode_messages,
    encode_message,
)


class BlackjackServer:
    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self.db = DatabaseManager("blackjack.db")
        self.table = BlackjackTable(self.db)

        # Mapa: obiekt socket -> nazwa zalogowanego użytkownika (lub None przed logowaniem)
        self.clients: dict[socket.socket, str | None] = {}
        self.clients_lock = threading.Lock()
        self.running = False

    def send_to_client(self, conn: socket.socket, payload: dict) -> None:
        try:
            conn.sendall(encode_message(payload))
        except OSError:
            pass

    def broadcast_state(self) -> None:
        """Wysyła aktualny stan stołu do wszystkich zalogowanych graczy."""
        packet = {
            "type": MSG_STATE_UPDATE,
            "state": self.table.get_state_snapshot(),
        }
        with self.clients_lock:
            logged_in_sockets = [
                conn for conn, user in self.clients.items() if user is not None
            ]

        for conn in logged_in_sockets:
            self.send_to_client(conn, packet)

    def _dealer_timer_loop(self) -> None:
        """Wątek w tle pilnujący odliczania czasu tury i faz gry."""
        last_broadcast = 0.0
        while self.running:
            time.sleep(0.5)
            state_changed = self.table.tick()
            now = time.time()

            # Rozsyłamy stan przy zmianie fazy/ruchu lub co 1s, aby odświeżać zegar u klientów
            if state_changed or (self.table.phase != PHASE_WAITING and now - last_broadcast >= 1.0):
                self.broadcast_state()
                last_broadcast = now

    def _handle_client(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        print(f"[NOWE POŁĄCZENIE] {addr[0]}:{addr[1]}")
        with self.clients_lock:
            self.clients[conn] = None

        buffer = ""
        try:
            while self.running:
                chunk = conn.recv(4096)
                if not chunk:
                    break

                buffer += chunk.decode(ENCODING, errors="replace")
                messages, buffer = decode_messages(buffer)

                for msg in messages:
                    self._process_message(conn, msg)
        except OSError:
            pass
        finally:
            self._disconnect_client(conn, addr)

    def _process_message(self, conn: socket.socket, data: dict) -> None:
        action = data.get("action")

        if action == ACTION_REGISTER:
            username = str(data.get("username", ""))
            password = str(data.get("password", ""))
            ok, message = self.db.register_user(username, password)
            self.send_to_client(conn, {
                "type": MSG_AUTH_RESULT,
                "action": ACTION_REGISTER,
                "success": ok,
                "message": message,
            })
            return

        if action == ACTION_LOGIN:
            username = str(data.get("username", "")).strip()
            password = str(data.get("password", ""))

            with self.clients_lock:
                if username in self.clients.values():
                    self.send_to_client(conn, {
                        "type": MSG_AUTH_RESULT,
                        "action": ACTION_LOGIN,
                        "success": False,
                        "message": "To konto jest już zalogowane na innym kliencie.",
                    })
                    return

            ok, message, stats = self.db.authenticate_user(username, password)
            if ok and stats:
                with self.clients_lock:
                    self.clients[conn] = stats["username"]
                print(f"[LOGOWANIE] Użytkownik '{stats['username']}' zalogowany.")

            self.send_to_client(conn, {
                "type": MSG_AUTH_RESULT,
                "action": ACTION_LOGIN,
                "success": ok,
                "message": message,
                "stats": stats,
            })

            if ok:
                self.send_to_client(conn, {
                    "type": MSG_STATE_UPDATE,
                    "state": self.table.get_state_snapshot(),
                })
            return

        # Kolejne akcje wymagają zalogowanego użytkownika
        with self.clients_lock:
            username = self.clients.get(conn)

        if not username:
            self.send_to_client(conn, {
                "type": MSG_ERROR,
                "message": "Musisz się najpierw zalogować.",
            })
            return

        if action == ACTION_SIT:
            ok, message = self.table.add_player(username)
            if ok:
                self.broadcast_state()
            else:
                self.send_to_client(conn, {"type": MSG_ERROR, "message": message})
            return

        if action == ACTION_GAME_MOVE:
            move = str(data.get("move", ""))
            try:
                amount = float(data.get("amount", 0.0))
            except (TypeError, ValueError):
                amount = 0.0

            ok, message = self.table.handle_move(username, move, amount)
            if ok:
                self.broadcast_state()
            else:
                self.send_to_client(conn, {"type": MSG_ERROR, "message": message})

    def _disconnect_client(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        with self.clients_lock:
            username = self.clients.pop(conn, None)

        if username:
            print(f"[ROZŁĄCZONO] Gracz '{username}' opuścił serwer.")
            self.table.remove_player(username)
            self.broadcast_state()
        else:
            print(f"[ROZŁĄCZONO] Niezalogowany klient {addr[0]}:{addr[1]}")

        try:
            conn.close()
        except OSError:
            pass

    def start(self) -> None:
        self.running = True
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((self.host, self.port))
        server_sock.listen()
        server_sock.settimeout(1.0)  # Umożliwia czyste zatrzymanie serwera przez Ctrl+C
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
        except OSError:
            local_ip = "127.0.0.1"

        print(f"=== SERWER URUCHOMIONY | Lokalnie: 127.0.0.1:{self.port} | W sieci LAN: {local_ip}:{self.port} ===")
        threading.Thread(target=self._dealer_timer_loop, daemon=True).start()

        try:
            while self.running:
                try:
                    conn, addr = server_sock.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr),
                        daemon=True,
                    ).start()
                except TimeoutError:
                    continue
        except KeyboardInterrupt:
            print("\nZamykanie serwera...")
        finally:
            self.running = False
            server_sock.close()


if __name__ == "__main__":
    BlackjackServer().start()