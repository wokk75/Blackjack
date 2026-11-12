import hashlib
import os
import sqlite3
import threading


class DatabaseManager:
    def __init__(self, db_path: str = "blackjack.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    balance REAL NOT NULL DEFAULT 1000.0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    net_profit REAL NOT NULL DEFAULT 0.0,
                    turnover REAL NOT NULL DEFAULT 0.0
                )
            """)
            conn.commit()

    @staticmethod
    def _hash_password(password: str, salt: str | None = None) -> str:
        if salt is None:
            salt = os.urandom(16).hex()
        digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return f"{salt}:{digest}"

    def register_user(self, username: str, password: str) -> tuple[bool, str]:
        username = username.strip()
        if len(username) < 3 or len(password) < 4:
            return False, "Login musi mieć min. 3 znaki, a hasło min. 4 znaki."

        pwd_hash = self._hash_password(password)
        try:
            with self.lock, self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, pwd_hash),
                )
                conn.commit()
            return True, "Rejestracja zakończona sukcesem."
        except sqlite3.IntegrityError:
            return False, "Taki użytkownik już istnieje."

    def authenticate_user(self, username: str, password: str) -> tuple[bool, str, dict | None]:
        with self.lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()

        if not row:
            return False, "Nieprawidłowy login lub hasło.", None

        salt, _ = row["password_hash"].split(":")
        if self._hash_password(password, salt) != row["password_hash"]:
            return False, "Nieprawidłowy login lub hasło.", None

        return True, "Zalogowano pomyślnie.", self.get_player_stats(row["username"])

    def get_player_stats(self, username: str) -> dict | None:
        with self.lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT username, balance, wins, losses, net_profit, turnover FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def place_bet(self, username: str, amount: float) -> bool:
        """Pobiera stawkę z salda i dolicza ją do obrotu gracza."""
        if amount <= 0:
            return False
        with self.lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT balance FROM users WHERE username = ?", (username,)
            ).fetchone()
            if not row or row["balance"] < amount:
                return False

            conn.execute(
                """
                UPDATE users
                SET balance = balance - ?, turnover = turnover + ?
                WHERE username = ?
                """,
                (amount, amount, username),
            )
            conn.commit()
        return True

    def settle_hand(self, username: str, bet: float, payout: float, outcome: str) -> None:
        """
        Rozlicza wynik rozdania w bazie:
        outcome: 'WIN', 'BLACKJACK', 'LOSE', 'PUSH'
        """
        profit_delta = payout - bet
        win_inc = 1 if outcome in ("WIN", "BLACKJACK") else 0
        loss_inc = 1 if outcome == "LOSE" else 0

        with self.lock, self._get_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET balance = balance + ?,
                    wins = wins + ?,
                    losses = losses + ?,
                    net_profit = net_profit + ?
                WHERE username = ?
                """,
                (payout, win_inc, loss_inc, profit_delta, username),
            )
            conn.commit()