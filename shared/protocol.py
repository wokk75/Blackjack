import json

HOST = "127.0.0.1"  # Localhost do testów na jednym komputerze
PORT = 5555
ENCODING = "utf-8"

# Typy akcji wysyłanych przez klienta
ACTION_REGISTER = "REGISTER"
ACTION_LOGIN = "LOGIN"
ACTION_SIT = "SIT"
ACTION_GAME_MOVE = "GAME_MOVE"

# Typy odpowiedzi wysyłanych przez serwer
MSG_AUTH_RESULT = "AUTH_RESULT"
MSG_STATE_UPDATE = "STATE_UPDATE"
MSG_ERROR = "ERROR"


def encode_message(data: dict) -> bytes:
    """Zamienia słownik Pythona na bajty JSON zakończone znakiem nowej linii."""
    json_str = json.dumps(data, ensure_ascii=False) + "\n"
    return json_str.encode(ENCODING)


def decode_messages(buffer: str) -> tuple[list[dict], str]:
    """
    Wyciąga pełne komunikaty JSON z bufora tekstowego.
    Zwraca listę odczytanych słowników oraz niekompletną resztę bufora.
    """
    messages = []
    while "\n" in buffer:
        line, buffer = buffer.split("\n", 1)
        if line.strip():
            messages.append(json.loads(line))
    return messages, buffer


# Ruchy gracza w Blackjacku (wysyłane w ACTION_GAME_MOVE)
MOVE_BET = "BET"
MOVE_HIT = "HIT"
MOVE_STAND = "STAND"
MOVE_DOUBLE = "DOUBLE"

# Fazy stołu (wysyłane w STATE_UPDATE)
PHASE_WAITING = "WAITING"          # Oczekiwanie na min. 1 gracza przy stole
PHASE_BETTING = "BETTING"          # Czas na postawienie zakładu
PHASE_PLAYER_TURNS = "PLAYER_TURNS"# Tury kolejnych graczy
PHASE_PAYOUT = "PAYOUT"            # Rozliczenie z krupierem i chwila przerwy przed kolejną rundą