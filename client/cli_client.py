import queue
import sys
import threading
from client.network import NetworkClient
from shared.protocol import (
    ACTION_LOGIN,
    ACTION_REGISTER,
    MOVE_BET,
    MOVE_DOUBLE,
    MOVE_HIT,
    MOVE_STAND,
    MSG_AUTH_RESULT,
    MSG_ERROR,
    MSG_STATE_UPDATE,
    PHASE_BETTING,
    PHASE_PAYOUT,
    PHASE_PLAYER_TURNS,
    PHASE_WAITING,
    HOST,
    PORT
)

SUIT_SYMBOLS = {"H": "♥", "D": "♦", "C": "♣", "S": "♠", "?": "?"}


def format_cards(cards: list[dict]) -> str:
    if not cards:
        return "brak"
    return " ".join(
        f"[{c['rank']}{SUIT_SYMBOLS.get(c['suit'], c['suit'])}]" for c in cards
    )


def print_stats(stats: dict) -> None:
    print(
        f"\n--- STATYSTYKI GRACZA: {stats['username']} ---\n"
        f"Saldo: {stats['balance']:.2f} | Wygrane: {stats['wins']} | "
        f"Przegrane: {stats['losses']} | Bilans: {stats['net_profit']:+.2f} | "
        f"Obrót: {stats['turnover']:.2f}\n"
        f"----------------------------------------"
    )


def render_table(state: dict, my_username: str) -> None:
    phase = state["phase"]
    time_left = state["time_left"]
    dealer = state["dealer"]
    common_hand = state.get("initial_player_hand", {})

    print("\n" + "=" * 55)
    print(f"FAZA GRY: {phase}  |  POZOSTAŁY CZAS: {time_left}s")
    print("=" * 55)
    print(f"KRUPIER ({dealer['score']} pkt): {format_cards(dealer['cards'])}")

    if common_hand.get("cards"):
        print(
            f"WSPÓLNE ROZDANIE STARTOWE ({common_hand['score']} pkt): "
            f"{format_cards(common_hand['cards'])}"
        )

    print("-" * 55)
    for seat in state["seats"]:
        marker = " (TY)" if seat["username"] == my_username else ""
        print(
            f"Gracz: {seat['username']}{marker} | Status: {seat['status']} | "
            f"Zakład: {seat['bet']:.2f} | Punkty: {seat['score']}\n"
            f"   Karty: {format_cards(seat['cards'])}"
        )
    print("-" * 55)

    if phase == PHASE_WAITING:
        print("Oczekiwanie na graczy przy stole...")
    elif phase == PHASE_BETTING:
        print("Komenda: bet <kwota>  (np. bet 100)")
    elif phase == PHASE_PLAYER_TURNS:
        if my_username in state.get("active_players", []):
            print("Twój ruch! Komendy: hit | stand | double")
        else:
            print("Oczekiwanie na decyzje pozostałych graczy...")
    elif phase == PHASE_PAYOUT:
        print("Rozliczenie rundy! Nowe rozdanie za chwilę...")


def auth_flow(client: NetworkClient) -> dict:
    while True:
        choice = input("\nWybierz opcję: [1] Logowanie  [2] Rejestracja  [q] Wyjście: ").strip().lower()
        if choice == "q":
            client.close()
            sys.exit(0)
        if choice not in ("1", "2"):
            continue

        username = input("Login: ").strip()
        password = input("Hasło: ").strip()

        if choice == "2":
            client.register(username, password)
        else:
            client.login(username, password)

        while True:
            msg = client.incoming_queue.get()
            if msg.get("type") == MSG_AUTH_RESULT:
                print(f"\n[SERWER] {msg['message']}")
                if msg.get("action") == ACTION_LOGIN and msg.get("success"):
                    return msg["stats"]
                break


def listener_worker(client: NetworkClient, username: str, stop_event: threading.Event) -> None:
    last_fingerprint = None
    while not stop_event.is_set():
        try:
            msg = client.incoming_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        msg_type = msg.get("type")
        if msg_type == MSG_ERROR:
            print(f"\n[BŁĄD] {msg['message']}")
        elif msg_type == MSG_STATE_UPDATE:
            state = msg["state"]
            # Odświeżamy ekran przy każdej zmianie stanu stołu lub co 5 sekund zegara,
            # aby nie przerywać wpisywania komend co 1 sekundę.
            fingerprint = (
                state["phase"],
                str(state["dealer"]),
                str([(s["username"], s["status"], s["bet"], s["cards"]) for s in state["seats"]]),
                state["time_left"] // 5,
            )
            if fingerprint != last_fingerprint:
                last_fingerprint = fingerprint
                render_table(state, username)
                for s in state["seats"]:
                    if s["username"] == username and s.get("stats") and state["phase"] == PHASE_PAYOUT:
                        print_stats(s["stats"])


def main() -> None:
    raw_addr = input(f"Podaj adres serwera (IP lub IP:PORT) [Enter = {HOST}:{PORT}]: ").strip()
    if not raw_addr:
        host, port = HOST, PORT
    elif ":" in raw_addr:
        host, port_str = raw_addr.split(":", 1)
        port = int(port_str)
    else:
        host, port = raw_addr, PORT

    client = NetworkClient(host=host, port=port)
    ok, info = client.connect()
    print(info)
    if not ok:
        return

    stats = auth_flow(client)
    username = stats["username"]
    print_stats(stats)

    input("Naciśnij ENTER, aby usiąść przy stole...")
    client.sit_at_table()

    stop_event = threading.Event()
    threading.Thread(
        target=listener_worker,
        args=(client, username, stop_event),
        daemon=True,
    ).start()

    try:
        while True:
            raw = input().strip().lower()
            if not raw:
                continue
            parts = raw.split()
            cmd = parts[0]

            if cmd in ("quit", "exit", "q"):
                break
            elif cmd in ("bet", "b") and len(parts) == 2:
                try:
                    amount = float(parts[1])
                    client.send_move(MOVE_BET, amount)
                except ValueError:
                    print("Podaj poprawną liczbę, np. bet 50")
            elif cmd in ("hit", "h"):
                client.send_move(MOVE_HIT)
            elif cmd in ("stand", "s"):
                client.send_move(MOVE_STAND)
            elif cmd in ("double", "d"):
                client.send_move(MOVE_DOUBLE)
            else:
                print("Nieznana komenda. Dostępne: bet <kwota>, hit, stand, double, quit")
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        client.close()
        print("Rozłączono z serwerem.")


if __name__ == "__main__":
    main()