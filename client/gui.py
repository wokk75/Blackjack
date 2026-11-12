import os
import queue
import sys

# Umożliwia uruchomienie zarówno przez `python -m client.main_client`, jak i bezpośrednio
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import customtkinter as ctk
from client.network import NetworkClient
from shared.protocol import (
    ACTION_LOGIN,
    ACTION_REGISTER,
    HOST,
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
    PORT,
)

SUIT_SYMBOLS = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}
STATUS_LABELS = {
    "WAITING": "Wybiera stawkę...",
    "BET_PLACED": "Zakład postawiony",
    "PLAYING": "Podejmuje decyzję...",
    "STOOD": "Pas (Stand)",
    "BUST": "Fura (>21 pkt)",
    "BLACKJACK": "BLACKJACK! (3:2)",
    "WIN": "WYGRANA!",
    "LOSE": "Przegrana",
    "PUSH": "Remis (Zwrot)",
}

PHASE_TITLES = {
    PHASE_WAITING: "Oczekiwanie na graczy przy stole",
    PHASE_BETTING: "Faza zakładów – wybierz stawkę",
    PHASE_PLAYER_TURNS: "Rozgrywka – tury graczy",
    PHASE_PAYOUT: "Rozliczenie z krupierem",
}


class CardWidget(ctk.CTkFrame):
    """Graficzna reprezentacja pojedynczej karty do gry."""

    def __init__(self, master, rank: str, suit: str):
        is_hidden = rank == "?" or suit == "?"
        bg_color = "#1e3a5f" if is_hidden else "#f8fafc"
        border_color = "#60a5fa" if is_hidden else "#cbd5e1"

        super().__init__(
            master,
            width=64,
            height=92,
            corner_radius=8,
            fg_color=bg_color,
            border_width=2,
            border_color=border_color,
        )
        self.pack_propagate(False)

        if is_hidden:
            ctk.CTkLabel(
                self,
                text="♠♥\n♦♣",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="#93c5fd",
            ).pack(expand=True)
        else:
            symbol = SUIT_SYMBOLS.get(suit, suit)
            color = "#dc2626" if suit in ("H", "D") else "#0f172a"

            ctk.CTkLabel(
                self,
                text=f"{rank}{symbol}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=color,
            ).pack(anchor="nw", padx=6, pady=(4, 0))

            ctk.CTkLabel(
                self,
                text=symbol,
                font=ctk.CTkFont(size=24, weight="bold"),
                text_color=color,
            ).pack(expand=True)


class AuthFrame(ctk.CTkFrame):
    """Ekran połączenia z serwerem, logowania oraz rejestracji."""

    def __init__(self, master, on_auth_submit):
        super().__init__(master, fg_color="transparent")
        self.on_auth_submit = on_auth_submit

        card = ctk.CTkFrame(self, width=420, corner_radius=16, fg_color="#1e2430")
        card.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            card,
            text="♠ BLACKJACK ONLINE ♥",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color="#f8fafc",
        ).pack(padx=40, pady=(30, 5))

        ctk.CTkLabel(
            card,
            text="Zaloguj się lub utwórz nowe konto gracza",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8",
        ).pack(padx=40, pady=(0, 20))

        self.server_entry = ctk.CTkEntry(
            card, width=320, height=38, placeholder_text="Adres serwera (IP:PORT)"
        )
        self.server_entry.insert(0, f"{HOST}:{PORT}")
        self.server_entry.pack(pady=6)

        self.username_entry = ctk.CTkEntry(
            card, width=320, height=38, placeholder_text="Login (min. 3 znaki)"
        )
        self.username_entry.pack(pady=6)

        self.password_entry = ctk.CTkEntry(
            card, width=320, height=38, placeholder_text="Hasło (min. 4 znaki)", show="*"
        )
        self.password_entry.pack(pady=6)
        self.password_entry.bind("<Return>", lambda _: self._submit(ACTION_LOGIN))

        self.status_label = ctk.CTkLabel(
            card,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f87171",
            wraplength=320,
        )
        self.status_label.pack(pady=(8, 4))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(pady=(10, 30))

        ctk.CTkButton(
            btn_row,
            text="Zaloguj się",
            width=152,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#16a34a",
            hover_color="#15803d",
            command=lambda: self._submit(ACTION_LOGIN),
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_row,
            text="Zarejestruj",
            width=152,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=lambda: self._submit(ACTION_REGISTER),
        ).pack(side="left", padx=8)

    def _submit(self, action: str) -> None:
        server_addr = self.server_entry.get().strip()
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        self.on_auth_submit(action, server_addr, username, password)

    def set_status(self, text: str, is_error: bool = True) -> None:
        self.status_label.configure(
            text=text, text_color="#f87171" if is_error else "#4ade80"
        )


class LobbyFrame(ctk.CTkFrame):
    """Panel statystyk gracza oraz przycisk dołączenia do stołu."""

    def __init__(self, master, on_sit_click):
        super().__init__(master, fg_color="transparent")
        self.on_sit_click = on_sit_click

        container = ctk.CTkFrame(self, width=540, corner_radius=16, fg_color="#1e2430")
        container.place(relx=0.5, rely=0.5, anchor="center")

        self.welcome_label = ctk.CTkLabel(
            container,
            text="Witaj, Gracz!",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        self.welcome_label.pack(padx=40, pady=(30, 5))

        ctk.CTkLabel(
            container,
            text="Twoje statystyki zapisane w bazie danych",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8",
        ).pack(pady=(0, 20))

        stats_grid = ctk.CTkFrame(container, fg_color="#141821", corner_radius=12)
        stats_grid.pack(padx=30, pady=10, fill="x")

        self.stat_boxes: dict[str, ctk.CTkLabel] = {}
        fields = [
            ("balance", "Aktualne saldo"),
            ("net_profit", "Bilans (Zysk/Strata)"),
            ("record", "Wygrane / Przegrane"),
            ("turnover", "Łączny obrót"),
        ]

        for idx, (key, title) in enumerate(fields):
            row, col = divmod(idx, 2)
            box = ctk.CTkFrame(stats_grid, fg_color="transparent")
            box.grid(row=row, column=col, padx=25, pady=16, sticky="w")

            ctk.CTkLabel(
                box, text=title, font=ctk.CTkFont(size=12), text_color="#94a3b8"
            ).pack(anchor="w")

            val_lbl = ctk.CTkLabel(
                box, text="-", font=ctk.CTkFont(size=20, weight="bold")
            )
            val_lbl.pack(anchor="w")
            self.stat_boxes[key] = val_lbl

        self.error_label = ctk.CTkLabel(
            container, text="", text_color="#f87171", font=ctk.CTkFont(size=12, weight="bold")
        )
        self.error_label.pack(pady=(10, 0))

        ctk.CTkButton(
            container,
            text="Usiądź przy stole (Maks. 4 graczy)",
            width=300,
            height=46,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#16a34a",
            hover_color="#15803d",
            command=self.on_sit_click,
        ).pack(pady=(15, 30))

    def update_stats(self, stats: dict) -> None:
        self.welcome_label.configure(text=f"Panel Gracza: {stats['username']}")
        self.stat_boxes["balance"].configure(
            text=f"{stats['balance']:.2f} PLN", text_color="#4ade80"
        )
        profit = stats["net_profit"]
        profit_color = "#4ade80" if profit >= 0 else "#f87171"
        self.stat_boxes["net_profit"].configure(
            text=f"{profit:+.2f} PLN", text_color=profit_color
        )
        self.stat_boxes["record"].configure(
            text=f"{stats['wins']} W / {stats['losses']} L"
        )
        self.stat_boxes["turnover"].configure(text=f"{stats['turnover']:.2f} PLN")

    def show_error(self, msg: str) -> None:
        self.error_label.configure(text=msg)


class TableFrame(ctk.CTkFrame):
    """Wieloosobowy stół do gry w Blackjacka z panelem akcji i zegarem tury."""

    def __init__(self, master, on_move_click):
        super().__init__(master, fg_color="#0f291e")
        self.on_move_click = on_move_click

        # 1. Górny pasek informacyjny (statystyki + faza gry + zegar)
        top_bar = ctk.CTkFrame(self, height=64, corner_radius=0, fg_color="#141821")
        top_bar.pack(fill="x", side="top")

        self.top_stats_label = ctk.CTkLabel(
            top_bar,
            text="Saldo: 0.00 | Bilans: +0.00 | Obrót: 0.00",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e2e8f0",
        )
        self.top_stats_label.pack(side="left", padx=20, pady=15)

        timer_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        timer_box.pack(side="right", padx=20, pady=8)

        self.phase_label = ctk.CTkLabel(
            timer_box,
            text="Oczekiwanie...",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#fbbf24",
        )
        self.phase_label.pack(anchor="e")

        self.timer_bar = ctk.CTkProgressBar(timer_box, width=220, height=10)
        self.timer_bar.set(0)
        self.timer_bar.pack(anchor="e", pady=(4, 0))

        # 2. Strefa Krupiera
        dealer_zone = ctk.CTkFrame(self, fg_color="#163b2b", corner_radius=16)
        dealer_zone.pack(pady=(18, 10), padx=30)

        self.dealer_title = ctk.CTkLabel(
            dealer_zone,
            text="KRUPIER (0 pkt)",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f8fafc",
        )
        self.dealer_title.pack(padx=30, pady=(12, 6))

        self.dealer_cards_box = ctk.CTkFrame(dealer_zone, fg_color="transparent", height=96)
        self.dealer_cards_box.pack(padx=30, pady=(0, 14))

        # 3. Strefa Miejsc Graczy (4 sloty obok siebie)
        self.seats_container = ctk.CTkFrame(self, fg_color="transparent")
        self.seats_container.pack(fill="both", expand=True, padx=20, pady=8)
        for col in range(4):
            self.seats_container.grid_columnconfigure(col, weight=1, uniform="seat")
        self.seats_container.grid_rowconfigure(0, weight=1)

        self.seat_widgets: list[dict] = []
        for idx in range(4):
            seat_frame = ctk.CTkFrame(
                self.seats_container,
                corner_radius=14,
                fg_color="#143326",
                border_width=2,
                border_color="#1e4d3a",
            )
            seat_frame.grid(row=0, column=idx, padx=8, pady=4, sticky="nsew")

            name_lbl = ctk.CTkLabel(
                seat_frame,
                text=f"Miejsce {idx + 1} (Wolne)",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="#94a3b8",
            )
            name_lbl.pack(pady=(12, 2))

            bet_lbl = ctk.CTkLabel(
                seat_frame, text="Zakład: -", font=ctk.CTkFont(size=13), text_color="#fbbf24"
            )
            bet_lbl.pack()

            status_lbl = ctk.CTkLabel(
                seat_frame, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#cbd5e1"
            )
            status_lbl.pack(pady=(2, 6))

            cards_box = ctk.CTkFrame(seat_frame, fg_color="transparent")
            cards_box.pack(expand=True, pady=4)

            score_lbl = ctk.CTkLabel(
                seat_frame, text="", font=ctk.CTkFont(size=14, weight="bold")
            )
            score_lbl.pack(pady=(4, 12))

            self.seat_widgets.append({
                "frame": seat_frame,
                "name": name_lbl,
                "bet": bet_lbl,
                "status": status_lbl,
                "cards": cards_box,
                "score": score_lbl,
            })

        # 4. Dolny panel akcji i komunikatów
        bottom_bar = ctk.CTkFrame(self, height=110, corner_radius=0, fg_color="#141821")
        bottom_bar.pack(fill="x", side="bottom")

        self.banner_label = ctk.CTkLabel(
            bottom_bar,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8",
        )
        self.banner_label.pack(pady=(8, 4))

        controls_row = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        controls_row.pack(pady=(2, 14))

        # Kontrolki zakładów
        self.bet_entry = ctk.CTkEntry(
            controls_row, width=100, height=38, placeholder_text="Stawka"
        )
        self.bet_entry.insert(0, "50")
        self.bet_entry.pack(side="left", padx=6)

        self.bet_btn = ctk.CTkButton(
            controls_row,
            text="Postaw zakład",
            width=130,
            height=38,
            fg_color="#d97706",
            hover_color="#b45309",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._handle_bet,
        )
        self.bet_btn.pack(side="left", padx=(0, 24))

        # Przyciski decyzji w trakcie tury
        self.hit_btn = ctk.CTkButton(
            controls_row,
            text="DOBIERZ (Hit)",
            width=140,
            height=40,
            fg_color="#16a34a",
            hover_color="#15803d",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: self.on_move_click(MOVE_HIT, 0.0),
        )
        self.hit_btn.pack(side="left", padx=6)

        self.stand_btn = ctk.CTkButton(
            controls_row,
            text="PAS (Stand)",
            width=140,
            height=40,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: self.on_move_click(MOVE_STAND, 0.0),
        )
        self.stand_btn.pack(side="left", padx=6)

        self.double_btn = ctk.CTkButton(
            controls_row,
            text="PODWÓJ (Double)",
            width=155,
            height=40,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: self.on_move_click(MOVE_DOUBLE, 0.0),
        )
        self.double_btn.pack(side="left", padx=6)

    def _handle_bet(self) -> None:
        try:
            amount = float(self.bet_entry.get().replace(",", "."))
            self.on_move_click(MOVE_BET, amount)
        except ValueError:
            self.set_banner("Wpisz poprawną kwotę zakładu!", is_error=True)

    def set_banner(self, text: str, is_error: bool = False) -> None:
        self.banner_label.configure(
            text=text, text_color="#f87171" if is_error else "#38bdf8"
        )

    @staticmethod
    def _render_cards(container: ctk.CTkFrame, cards: list[dict]) -> None:
        for child in container.winfo_children():
            child.destroy()
        for card in cards:
            CardWidget(container, card["rank"], card["suit"]).pack(side="left", padx=3)

    def update_state(self, state: dict, my_username: str) -> None:
        phase = state["phase"]
        time_left = state["time_left"]
        active_player = state.get("active_player")

        # Aktualizacja paska czasu i fazy
        phase_text = PHASE_TITLES.get(phase, phase)
        if phase != PHASE_WAITING:
            self.phase_label.configure(text=f"{phase_text} ({time_left}s)")
            max_time = 6.0 if phase == PHASE_PAYOUT else 15.0
            self.timer_bar.set(min(1.0, max(0.0, time_left / max_time)))
        else:
            self.phase_label.configure(text=phase_text)
            self.timer_bar.set(0)

        # Karty krupiera
        dealer = state["dealer"]
        self.dealer_title.configure(text=f"KRUPIER ({dealer['score']} pkt)")
        self._render_cards(self.dealer_cards_box, dealer["cards"])

        # Miejsca graczy
        seats = state["seats"]
        my_seat = None

        for idx in range(4):
            w = self.seat_widgets[idx]
            if idx < len(seats):
                seat = seats[idx]
                uname = seat["username"]
                is_me = uname == my_username
                is_turn = phase == PHASE_PLAYER_TURNS and active_player == uname

                if is_me:
                    my_seat = seat
                    if seat.get("stats"):
                        st = seat["stats"]
                        self.top_stats_label.configure(
                            text=(
                                f"Gracz: {uname}  |  Saldo: {st['balance']:.2f} PLN  |  "
                                f"Bilans: {st['net_profit']:+.2f} PLN  |  "
                                f"W/L: {st['wins']}/{st['losses']}  |  Obrót: {st['turnover']:.2f} PLN"
                            )
                        )

                border_col = "#fbbf24" if is_turn else ("#38bdf8" if is_me else "#1e4d3a")
                w["frame"].configure(border_color=border_col, fg_color="#183d2e")
                w["name"].configure(
                    text=f"{uname} {'(TY)' if is_me else ''}",
                    text_color="#fbbf24" if is_turn else "#f8fafc",
                )
                w["bet"].configure(text=f"Zakład: {seat['bet']:.2f} PLN")

                raw_status = seat["status"]
                status_pl = STATUS_LABELS.get(raw_status, raw_status)
                status_color = (
                    "#4ade80" if raw_status in ("WIN", "BLACKJACK")
                    else "#f87171" if raw_status in ("LOSE", "BUST")
                    else "#fbbf24" if is_turn
                    else "#cbd5e1"
                )
                w["status"].configure(text=status_pl, text_color=status_color)
                self._render_cards(w["cards"], seat["cards"])
                w["score"].configure(
                    text=f"Punkty: {seat['score']}" if seat["cards"] else ""
                )
            else:
                w["frame"].configure(border_color="#1e4d3a", fg_color="#122b20")
                w["name"].configure(text=f"Miejsce {idx + 1} (Wolne)", text_color="#64748b")
                w["bet"].configure(text="Zakład: -")
                w["status"].configure(text="")
                self._render_cards(w["cards"], [])
                w["score"].configure(text="")

        # Zarządzanie stanem przycisków akcji (aktywne tylko w odpowiednim momencie)
        can_bet = (
            phase == PHASE_BETTING
            and my_seat is not None
            and my_seat["status"] == "WAITING"
        )
        is_my_turn = (
            phase == PHASE_PLAYER_TURNS
            and active_player == my_username
            and my_seat is not None
        )
        can_double = (
            is_my_turn
            and len(my_seat["cards"]) == 2
            and my_seat.get("stats", {}).get("balance", 0.0) >= my_seat["bet"]
        )

        self.bet_entry.configure(state="normal" if can_bet else "disabled")
        self.bet_btn.configure(state="normal" if can_bet else "disabled")
        self.hit_btn.configure(state="normal" if is_my_turn else "disabled")
        self.stand_btn.configure(state="normal" if is_my_turn else "disabled")
        self.double_btn.configure(state="normal" if can_double else "disabled")

        # Podpowiedź na dolnym pasku
        if can_bet:
            self.set_banner("Wpisz stawkę i kliknij 'Postaw zakład'.")
        elif is_my_turn:
            self.set_banner("TWOJA TURA! Wybierz decyzję przed upływem czasu.")
        elif phase == PHASE_PLAYER_TURNS and active_player:
            self.set_banner(f"Tura gracza {active_player} – oczekiwanie na ruch...")
        elif phase == PHASE_PAYOUT:
            self.set_banner("Rozliczenie rundy! Za chwilę rozpocznie się nowe rozdanie.")


class BlackjackApp(ctk.CTk):
    """Główne okno aplikacji klienckiej."""

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Blackjack Online – Projekt Zaliczeniowy")
        self.geometry("1120x720")
        self.minsize(980, 640)

        self.network = NetworkClient()
        self.username: str | None = None
        self.stats: dict | None = None

        self.auth_frame = AuthFrame(self, self._on_auth_submit)
        self.lobby_frame = LobbyFrame(self, self._on_sit_click)
        self.table_frame = TableFrame(self, self._on_move_click)

        self.current_view = self.auth_frame
        self.current_view.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_network)

    def _switch_view(self, target_frame: ctk.CTkFrame) -> None:
        if self.current_view is not target_frame:
            self.current_view.pack_forget()
            self.current_view = target_frame
            self.current_view.pack(fill="both", expand=True)

    def _on_auth_submit(
        self, action: str, server_addr: str, username: str, password: str
    ) -> None:
        if not username or not password:
            self.auth_frame.set_status("Podaj login oraz hasło.")
            return

        if ":" in server_addr:
            host, port_str = server_addr.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                self.auth_frame.set_status("Niepoprawny numer portu.")
                return
        else:
            host, port = server_addr or HOST, PORT

        if not self.network.connected:
            self.network.host = host
            self.network.port = port
            ok, msg = self.network.connect()
            if not ok:
                self.auth_frame.set_status(msg)
                return

        if action == ACTION_REGISTER:
            self.network.register(username, password)
        else:
            self.network.login(username, password)

    def _on_sit_click(self) -> None:
        self.network.sit_at_table()

    def _on_move_click(self, move: str, amount: float) -> None:
        self.network.send_move(move, amount)

    def _poll_network(self) -> None:
        try:
            while True:
                msg = self.network.incoming_queue.get_nowait()
                self._handle_packet(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_network)

    def _handle_packet(self, msg: dict) -> None:
        msg_type = msg.get("type")

        if msg_type == MSG_AUTH_RESULT:
            success = msg.get("success", False)
            text = msg.get("message", "")
            if msg.get("action") == ACTION_LOGIN and success:
                self.stats = msg["stats"]
                self.username = self.stats["username"]
                self.lobby_frame.update_stats(self.stats)
                self._switch_view(self.lobby_frame)
            else:
                self.auth_frame.set_status(text, is_error=not success)

        elif msg_type == MSG_ERROR:
            err_text = msg.get("message", "Błąd serwera.")
            if self.current_view is self.auth_frame:
                self.auth_frame.set_status(err_text, is_error=True)
            elif self.current_view is self.lobby_frame:
                self.lobby_frame.show_error(err_text)
            elif self.current_view is self.table_frame:
                self.table_frame.set_banner(err_text, is_error=True)

        elif msg_type == MSG_STATE_UPDATE and self.username:
            state = msg["state"]
            seated_users = [s["username"] for s in state["seats"]]
            if self.username in seated_users:
                self._switch_view(self.table_frame)
                self.table_frame.update_state(state, self.username)

    def _on_close(self) -> None:
        self.network.close()
        self.destroy()