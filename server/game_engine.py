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
        self.initial_player_hand: list[Card] = []
        self.phase: str = PHASE_WAITING
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

            self.seats.pop(idx)

            if not self.seats:
                self.phase = PHASE_WAITING
                self.dealer_hand.clear()
                self.initial_player_hand.clear()
                return

            if self.phase == PHASE_BETTING and all(p.status == "BET_PLACED" for p in self.seats):
                self._deal_initial_cards()
            elif self.phase == PHASE_PLAYER_TURNS:
                self._check_all_players_done()

    def _start_betting_phase(self) -> None:
        self.phase = PHASE_BETTING
        self.dealer_hand.clear()
        self.initial_player_hand.clear()
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
                if player.status != "PLAYING":
                    return False, "Zakończyłeś już swoje decyzje w tym rozdaniu."

                if move == MOVE_HIT:
                    player.hand.append(self.shoe.draw())
                    score = calculate_score(player.hand)
                    if score > 21:
                        player.status = "BUST"
                    elif score == 21:
                        player.status = "STOOD"
                    self._check_all_players_done()
                    return True, "Dobrano kartę."

                if move == MOVE_STAND:
                    player.status = "STOOD"
                    self._check_all_players_done()
                    return True, "Pas (Stand)."

                if move == MOVE_DOUBLE:
                    if len(player.hand) != 2:
                        return False, "Podwojenie możliwe tylko przy 2 kartach."
                    if not self.db.place_bet(username, player.bet):
                        return False, "Za mało środków na podwojenie stawki."
                    player.bet *= 2
                    player.hand.append(self.shoe.draw())
                    player.status = "BUST" if calculate_score(player.hand) > 21 else "STOOD"
                    self._check_all_players_done()
                    return True, "Podwojono stawkę i dobrano 1 kartę."

            return False, "Niedozwolona akcja w obecnym momencie gry."

    def _deal_initial_cards(self) -> None:
        active_bettors = [p for p in self.seats if p.bet > 0]
        if not active_bettors:
            self._start_betting_phase()
            return

        # Krupier losuje jedną wspólną rękę dla graczy oraz jedną dla kasyna
        self.initial_player_hand = [self.shoe.draw(), self.shoe.draw()]
        self.dealer_hand = [self.shoe.draw(), self.shoe.draw()]

        is_natural_bj = calculate_score(self.initial_player_hand) == 21

        for p in active_bettors:
            p.hand = [Card(c.suit, c.rank) for c in self.initial_player_hand]
            p.status = "BLACKJACK" if is_natural_bj else "PLAYING"

        self.phase = PHASE_PLAYER_TURNS
        self.deadline = time.time() + self.TURN_TIME
        self._check_all_players_done()

    def _check_all_players_done(self) -> None:
        """Jeśli żaden gracz nie ma już statusu PLAYING, krupier od razu kończy rozdanie."""
        if all(p.status != "PLAYING" for p in self.seats):
            self._play_dealer_and_settle()

    def _play_dealer_and_settle(self) -> None:
        self.phase = PHASE_PAYOUT

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

            if self.phase == PHASE_PLAYER_TURNS:
                # Upłynęło 15s -> wszyscy niezdecydowani gracze automatycznie pasują
                for p in self.seats:
                    if p.status == "PLAYING":
                        p.status = "STOOD"
                self._play_dealer_and_settle()
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

            return {
                "phase": self.phase,
                "active_players": [p.username for p in self.seats if p.status == "PLAYING"],
                "time_left": max(0, int(round(self.deadline - time.time()))),
                "dealer": {
                    "cards": dealer_cards,
                    "score": dealer_points,
                },
                "initial_player_hand": {
                    "cards": [c.to_dict() for c in self.initial_player_hand],
                    "score": calculate_score(self.initial_player_hand),
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