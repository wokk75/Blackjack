from dataclasses import dataclass, field
import random
import threading
import time
from server.database import DatabaseManager
from shared.protocol import (
    MOVE_BET,
    MOVE_DOUBLE,
    MOVE_HIT,
    MOVE_STAND,
    PHASE_BETTING,
    PHASE_PAYOUT,
    PHASE_PLAYER_TURNS,
    PHASE_WAITING,
)

SUITS = ["H", "D", "C", "S"]  # Kier, Karo, Trefl, Pik
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]


@dataclass
class Card:
    suit: str
    rank: str

    def to_dict(self) -> dict:
        return {"suit": self.suit, "rank": self.rank}


class Shoe:
    """Zestaw 4 talii kart zarządzany przez automatycznego krupiera."""

    def __init__(self, num_decks: int = 4):
        self.num_decks = num_decks
        self.cards: list[Card] = []
        self.reshuffle()

    def reshuffle(self) -> None:
        self.cards = [
            Card(suit, rank)
            for _ in range(self.num_decks)
            for suit in SUITS
            for rank in RANKS
        ]
        random.shuffle(self.cards)

    def draw(self) -> Card:
        if len(self.cards) < 25:
            self.reshuffle()
        return self.cards.pop()


def calculate_score(hand: list[Card]) -> int:
    total = 0
    aces = 0
    for card in hand:
        if card.rank in ("J", "Q", "K"):
            total += 10
        elif card.rank == "A":
            aces += 1
            total += 11
        else:
            total += int(card.rank)

    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


@dataclass
class PlayerSeat:
    username: str
    bet: float = 0.0
    hand: list[Card] = field(default_factory=list)
    status: str = "WAITING"  # WAITING, BET_PLACED, PLAYING, STOOD, BUST, BLACKJACK, WIN, LOSE, PUSH


class BlackjackTable:
    MAX_SEATS = 4
    BETTING_TIME = 15.0
    TURN_TIME = 15.0
    PAYOUT_TIME = 6.0

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.lock = threading.RLock()
        self.shoe = Shoe(num_decks=4)
        self.seats: list[PlayerSeat] = []
        self.dealer_hand: list[Card] = []
        self.phase: str = PHASE_WAITING
        self.active_player_idx: int | None = None
        self.deadline: float = 0.0

    def add_player(self, username: str) -> tuple[bool, str]:
        with self.lock:
            if any(p.username == username for p in self.seats):
                return True, "Już siedzisz przy stole."
            if len(self.seats) >= self.MAX_SEATS:
                return False, "Stół jest pełny (maks. 4 graczy)."

            self.seats.append(PlayerSeat(username=username))
            if self.phase == PHASE_WAITING:
                self._start_betting_phase()
            return True, "Dołączono do stołu."

    def remove_player(self, username: str) -> None:
        with self.lock:
            idx = next((i for i, p in enumerate(self.seats) if p.username == username), None)
            if idx is None:
                return

            was_active = (self.phase == PHASE_PLAYER_TURNS and self.active_player_idx == idx)
            self.seats.pop(idx)

            if not self.seats:
                self.phase = PHASE_WAITING
                self.dealer_hand.clear()
                self.active_player_idx = None
                return

            if self.phase == PHASE_BETTING and all(p.status == "BET_PLACED" for p in self.seats):
                self._deal_initial_cards()
                return

            if self.phase == PHASE_PLAYER_TURNS:
                if self.active_player_idx is not None and idx < self.active_player_idx:
                    self.active_player_idx -= 1
                if was_active and self.active_player_idx is not None:
                    self.active_player_idx -= 1
                    self._advance_turn()

    def _start_betting_phase(self) -> None:
        self.phase = PHASE_BETTING
        self.dealer_hand.clear()
        self.active_player_idx = None
        for p in self.seats:
            p.bet = 0.0
            p.hand.clear()
            p.status = "WAITING"
        self.deadline = time.time() + self.BETTING_TIME

    def handle_move(self, username: str, move: str, amount: float = 0.0) -> tuple[bool, str]:
        with self.lock:
            player = next((p for p in self.seats if p.username == username), None)
            if not player:
                return False, "Nie siedzisz przy stole."

            if self.phase == PHASE_BETTING and move == MOVE_BET:
                if player.status == "BET_PLACED":
                    return False, "Zakład został już przyjęty."
                if not self.db.place_bet(username, amount):
                    return False, "Niewystarczające saldo lub błędna stawka."
                player.bet = amount
                player.status = "BET_PLACED"

                if all(p.status == "BET_PLACED" for p in self.seats):
                    self._deal_initial_cards()
                return True, f"Postawiono {amount}."

            if self.phase == PHASE_PLAYER_TURNS:
                if self.active_player_idx is None or self.seats[self.active_player_idx].username != username:
                    return False, "Teraz nie jest Twoja tura."

                if move == MOVE_HIT:
                    player.hand.append(self.shoe.draw())
                    score = calculate_score(player.hand)
                    if score > 21:
                        player.status = "BUST"
                        self._advance_turn()
                    elif score == 21:
                        player.status = "STOOD"
                        self._advance_turn()
                    else:
                        self.deadline = time.time() + self.TURN_TIME
                    return True, "Dobrano kartę."

                if move == MOVE_STAND:
                    player.status = "STOOD"
                    self._advance_turn()
                    return True, "Pas (Stand)."

                if move == MOVE_DOUBLE:
                    if len(player.hand) != 2:
                        return False, "Podwojenie możliwe tylko przy 2 kartach."
                    if not self.db.place_bet(username, player.bet):
                        return False, "Za mało środków na podwojenie stawki."
                    player.bet *= 2
                    player.hand.append(self.shoe.draw())
                    player.status = "BUST" if calculate_score(player.hand) > 21 else "STOOD"
                    self._advance_turn()
                    return True, "Podwojono stawkę i dobrano 1 kartę."

            return False, "Niedozwolona akcja w obecnym momencie gry."

    def _deal_initial_cards(self) -> None:
        active_bettors = [p for p in self.seats if p.bet > 0]
        if not active_bettors:
            self._start_betting_phase()
            return

        # Każdy gracz otrzymuje własne, niezależne 2 karty z buta
        for p in active_bettors:
            p.hand = [self.shoe.draw(), self.shoe.draw()]
            p.status = "BLACKJACK" if calculate_score(p.hand) == 21 else "PLAYING"

        self.dealer_hand = [self.shoe.draw(), self.shoe.draw()]
        self.phase = PHASE_PLAYER_TURNS
        self.active_player_idx = -1
        self._advance_turn()

    def _advance_turn(self) -> None:
        if self.active_player_idx is None:
            self.active_player_idx = -1

        while True:
            self.active_player_idx += 1
            if self.active_player_idx >= len(self.seats):
                self._play_dealer_and_settle()
                return
            if self.seats[self.active_player_idx].status == "PLAYING":
                self.deadline = time.time() + self.TURN_TIME
                return

    def _play_dealer_and_settle(self) -> None:
        self.phase = PHASE_PAYOUT
        self.active_player_idx = None

        if any(p.status in ("STOOD", "BLACKJACK") for p in self.seats):
            while calculate_score(self.dealer_hand) < 17:
                self.dealer_hand.append(self.shoe.draw())

        dealer_score = calculate_score(self.dealer_hand)
        dealer_bj = len(self.dealer_hand) == 2 and dealer_score == 21

        for p in self.seats:
            if p.bet <= 0:
                continue
            p_score = calculate_score(p.hand)

            if p.status == "BUST":
                p.status = "LOSE"
                self.db.settle_hand(p.username, p.bet, 0.0, "LOSE")
            elif p.status == "BLACKJACK" and not dealer_bj:
                p.status = "BLACKJACK"
                self.db.settle_hand(p.username, p.bet, p.bet * 2.5, "BLACKJACK")
            elif dealer_score > 21 or p_score > dealer_score:
                p.status = "WIN"
                self.db.settle_hand(p.username, p.bet, p.bet * 2.0, "WIN")
            elif p_score == dealer_score:
                p.status = "PUSH"
                self.db.settle_hand(p.username, p.bet, p.bet, "PUSH")
            else:
                p.status = "LOSE"
                self.db.settle_hand(p.username, p.bet, 0.0, "LOSE")

        self.deadline = time.time() + self.PAYOUT_TIME

    def tick(self) -> bool:
        with self.lock:
            if self.phase == PHASE_WAITING or time.time() < self.deadline:
                return False

            if self.phase == PHASE_BETTING:
                self._deal_initial_cards()
                return True

            if self.phase == PHASE_PLAYER_TURNS and self.active_player_idx is not None:
                # Koniec czasu tury aktywnego gracza -> automatyczny PASS
                self.seats[self.active_player_idx].status = "STOOD"
                self._advance_turn()
                return True

            if self.phase == PHASE_PAYOUT:
                self._start_betting_phase()
                return True

            return False

    def get_state_snapshot(self) -> dict:
        with self.lock:
            hide_hole_card = self.phase == PHASE_PLAYER_TURNS and len(self.dealer_hand) == 2
            dealer_cards = []
            for idx, card in enumerate(self.dealer_hand):
                if idx == 1 and hide_hole_card:
                    dealer_cards.append({"suit": "?", "rank": "?"})
                else:
                    dealer_cards.append(card.to_dict())

            dealer_points = (
                calculate_score([self.dealer_hand[0]])
                if hide_hole_card
                else calculate_score(self.dealer_hand)
            )

            active_user = (
                self.seats[self.active_player_idx].username
                if self.phase == PHASE_PLAYER_TURNS and self.active_player_idx is not None
                else None
            )

            return {
                "phase": self.phase,
                "active_player": active_user,
                "active_players": [active_user] if active_user else [],
                "time_left": max(0, int(round(self.deadline - time.time()))),
                "dealer": {
                    "cards": dealer_cards,
                    "score": dealer_points,
                },
                "seats": [
                    {
                        "username": p.username,
                        "bet": p.bet,
                        "status": p.status,
                        "cards": [c.to_dict() for c in p.hand],
                        "score": calculate_score(p.hand),
                        "stats": self.db.get_player_stats(p.username),
                    }
                    for p in self.seats
                ],
            }