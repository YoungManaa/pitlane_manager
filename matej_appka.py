from __future__ import annotations

import json
import math
import tkinter as tk
from dataclasses import asdict, dataclass
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Optional


APP_TITLE = "Enduro Team & Cart Manager"
SCHEMA_VERSION = 2

CATEGORY_COLORS = {
    "Purple": "#8e44ad",
    "Green": "#27ae60",
    "Blue": "#2980b9",
    "Yellow": "#f1c40f",
    "Orange": "#e67e22",
    "Red": "#c0392b",
}

TEXT_COLORS = {
    "Purple": "white",
    "Green": "white",
    "Blue": "white",
    "Yellow": "#111111",
    "Orange": "#111111",
    "Red": "white",
}

GOOD_CATEGORIES = {"Purple", "Green"}
CATEGORY_PRIORITY = {
    "Purple": 0,
    "Green": 1,
    "Blue": 2,
    "Yellow": 3,
    "Orange": 4,
    "Red": 5,
}


@dataclass
class Cart:
    number: str
    category: str = "Blue"
    lap_time: Optional[float] = None
    team_id: Optional[str] = None
    pit_row: Optional[int] = None


@dataclass
class Team:
    team_id: str
    cart_number: str


@dataclass
class PitEvent:
    sequence: int
    timestamp: str
    team_id: str
    row: int
    incoming_cart: str
    outgoing_cart: str


def parse_time(value: str) -> Optional[float]:
    """Parse seconds or minutes:seconds; a blank value means unknown."""
    text = value.strip()
    if not text:
        return None
    try:
        if ":" in text:
            parts = text.split(":")
            if len(parts) != 2:
                raise ValueError
            minutes = int(parts[0])
            seconds = float(parts[1])
            if minutes < 0 or seconds < 0 or seconds >= 60:
                raise ValueError
            return minutes * 60 + seconds
        seconds = float(text)
        if seconds < 0:
            raise ValueError
        return seconds
    except ValueError as exc:
        raise ValueError(
            "Enter time as seconds (102.351) or minutes:seconds (1:42.351)."
        ) from exc


def format_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes}:{remaining:06.3f}"


def natural_key(value: str) -> tuple[int, object]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value.casefold())


class SessionModel:
    """Pure session logic, intentionally independent from Tkinter."""

    def __init__(self, row_count: int = 3) -> None:
        if row_count < 1:
            raise ValueError("A session needs at least one pit row.")
        self.row_count = row_count
        self.carts: dict[str, Cart] = {}
        self.teams: dict[str, Team] = {}
        self.pit_rows: dict[int, list[str]] = {
            row: [] for row in range(1, row_count + 1)
        }
        self.reserve: list[str] = []
        self.events: list[PitEvent] = []

    @classmethod
    def create(
        cls,
        team_count: int,
        cart_count: int,
        row_count: int,
        team_names: Optional[list[str]] = None,
    ) -> SessionModel:
        if team_count < 1:
            raise ValueError("Choose at least one team.")
        if row_count < 1:
            raise ValueError("Choose at least one pit row.")
        if cart_count < team_count + row_count:
            raise ValueError(
                "You need at least one active cart per team and one waiting cart "
                "per pit row."
            )
        if max(team_count, cart_count) > 200 or row_count > 12:
            raise ValueError("Maximum: 200 teams/carts and 12 pit rows.")

        supplied_names = list(team_names or [])
        while supplied_names and not supplied_names[-1].strip():
            supplied_names.pop()
        if len(supplied_names) > team_count:
            raise ValueError(
                f"You entered {len(supplied_names)} team names for {team_count} teams."
            )

        resolved_names = []
        for index in range(1, team_count + 1):
            supplied = supplied_names[index - 1].strip() if index <= len(supplied_names) else ""
            resolved_names.append(supplied or f"Team {index}")
        if len(set(resolved_names)) != len(resolved_names):
            raise ValueError("Every team name/ID must be unique.")

        model = cls(row_count)
        for number in range(1, cart_count + 1):
            model.carts[str(number)] = Cart(number=str(number))

        for index, team_id in enumerate(resolved_names, start=1):
            cart_number = str(index)
            model.teams[team_id] = Team(team_id=team_id, cart_number=cart_number)
            model.carts[cart_number].team_id = team_id

        waiting = [str(number) for number in range(team_count + 1, cart_count + 1)]
        for index, cart_number in enumerate(waiting):
            row = index % row_count + 1
            model.pit_rows[row].append(cart_number)
            model.carts[cart_number].pit_row = row

        model.validate()
        return model

    def validate(self) -> None:
        """Raise ValueError when a cart appears in more than one place."""
        occupied: set[str] = set()
        for key, team in self.teams.items():
            if key != team.team_id:
                raise ValueError("Team IDs are inconsistent.")
            if not team.team_id.strip():
                raise ValueError("Team IDs cannot be blank.")
            if team.cart_number not in self.carts:
                raise ValueError(f"Team {team.team_id} has an unknown cart.")
            if team.cart_number in occupied:
                raise ValueError(f"Cart #{team.cart_number} is assigned twice.")
            occupied.add(team.cart_number)
            cart = self.carts[team.cart_number]
            if cart.team_id != team.team_id or cart.pit_row is not None:
                raise ValueError(f"Cart #{cart.number} has an invalid team assignment.")

        if set(self.pit_rows) != set(range(1, self.row_count + 1)):
            raise ValueError("Pit-row numbering is inconsistent.")

        for row, queue in self.pit_rows.items():
            for number in queue:
                if number not in self.carts:
                    raise ValueError(f"Row {row} contains an unknown cart.")
                if number in occupied:
                    raise ValueError(f"Cart #{number} appears in more than one place.")
                occupied.add(number)
                cart = self.carts[number]
                if cart.pit_row != row or cart.team_id is not None:
                    raise ValueError(f"Cart #{number} has an invalid pit-row assignment.")

        for number in self.reserve:
            if number not in self.carts:
                raise ValueError("The reserve contains an unknown cart.")
            if number in occupied:
                raise ValueError(f"Cart #{number} appears in more than one place.")
            occupied.add(number)
            cart = self.carts[number]
            if cart.team_id is not None or cart.pit_row is not None:
                raise ValueError(f"Reserve cart #{number} has an invalid assignment.")

        missing = set(self.carts) - occupied
        if missing:
            raise ValueError(f"Unassigned cart(s): {', '.join(sorted(missing))}")

    def cart_location(self, number: str) -> str:
        cart = self.carts[number]
        if cart.team_id is not None:
            return f"Racing — {cart.team_id}"
        if cart.pit_row is not None:
            position = self.pit_rows[cart.pit_row].index(number) + 1
            return f"Row {cart.pit_row} — position {position}"
        return "Reserve"

    def detach_cart(self, number: str) -> None:
        cart = self.carts[number]
        if cart.team_id is not None:
            raise ValueError("An active team cart cannot be moved directly.")
        if cart.pit_row is not None:
            queue = self.pit_rows[cart.pit_row]
            if number in queue:
                queue.remove(number)
        elif number in self.reserve:
            self.reserve.remove(number)
        cart.pit_row = None

    def move_cart(self, number: str, destination: str) -> None:
        """Move a waiting cart to another location, preserving order on no-op saves."""
        if number not in self.carts:
            raise ValueError("Unknown cart.")
        cart = self.carts[number]
        if cart.team_id is not None:
            raise ValueError("The cart is currently being driven by a team.")

        current_destination = (
            "Reserve" if cart.pit_row is None else f"Row {cart.pit_row}"
        )
        if destination == current_destination:
            return

        self.place_cart(number, destination)

    def place_cart(
        self,
        number: str,
        destination: str,
        index: Optional[int] = None,
    ) -> None:
        """Place a waiting cart at an exact queue/reserve position."""
        if number not in self.carts:
            raise ValueError("Unknown cart.")
        cart = self.carts[number]
        if cart.team_id is not None:
            raise ValueError("The cart is currently being driven by a team.")

        target_row: Optional[int] = None
        if destination == "Reserve":
            pass
        elif destination.startswith("Row "):
            try:
                target_row = int(destination.split()[1])
            except (IndexError, ValueError) as exc:
                raise ValueError("Invalid pit-row destination.") from exc
            if target_row not in self.pit_rows:
                raise ValueError("That pit row does not exist.")
        else:
            raise ValueError("Invalid cart destination.")

        self.detach_cart(number)
        target: list[str]
        if target_row is None:
            target = self.reserve
        else:
            target = self.pit_rows[target_row]
            cart.pit_row = target_row

        if index is None:
            target.append(number)
        else:
            target.insert(max(0, min(int(index), len(target))), number)
        self.validate()

    def pit_exchange(self, team_id: str, row: int) -> PitEvent:
        if team_id not in self.teams:
            raise ValueError("Select a valid team.")
        if row not in self.pit_rows:
            raise ValueError("That pit row does not exist.")
        if not self.pit_rows[row]:
            raise ValueError(
                f"Row {row} is empty. Move a waiting cart into it before pitting."
            )

        team = self.teams[team_id]
        incoming_number = team.cart_number
        outgoing_number = self.pit_rows[row].pop(0)
        incoming_cart = self.carts[incoming_number]
        outgoing_cart = self.carts[outgoing_number]

        incoming_cart.team_id = None
        incoming_cart.pit_row = row
        self.pit_rows[row].append(incoming_number)
        outgoing_cart.pit_row = None
        outgoing_cart.team_id = team_id
        team.cart_number = outgoing_number

        event = PitEvent(
            sequence=len(self.events) + 1,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            team_id=team_id,
            row=row,
            incoming_cart=incoming_number,
            outgoing_cart=outgoing_number,
        )
        self.events.append(event)
        self.validate()
        return event

    def rename_team(self, old_id: str, new_id: str) -> None:
        new_id = new_id.strip()
        if old_id not in self.teams:
            raise ValueError("Select a team first.")
        if not new_id:
            raise ValueError("Team ID cannot be blank.")
        if new_id != old_id and new_id in self.teams:
            raise ValueError("That team ID already exists.")
        if new_id == old_id:
            return
        team = self.teams.pop(old_id)
        team.team_id = new_id
        self.teams[new_id] = team
        self.carts[team.cart_number].team_id = new_id
        for event in self.events:
            if event.team_id == old_id:
                event.team_id = new_id
        self.validate()

    def add_team(self, team_id: str, cart_number: str) -> None:
        team_id = team_id.strip()
        if not team_id:
            raise ValueError("Team ID cannot be blank.")
        if team_id in self.teams:
            raise ValueError("That team ID already exists.")
        if cart_number not in self.reserve:
            raise ValueError("A new team must start with a reserve cart.")
        self.reserve.remove(cart_number)
        cart = self.carts[cart_number]
        cart.team_id = team_id
        self.teams[team_id] = Team(team_id=team_id, cart_number=cart_number)
        self.validate()

    def delete_team(self, team_id: str) -> None:
        if team_id not in self.teams:
            raise ValueError("Select a team first.")
        team = self.teams.pop(team_id)
        cart = self.carts[team.cart_number]
        cart.team_id = None
        self.reserve.append(cart.number)
        self.validate()

    def add_cart(self, number: str, category: str, destination: str) -> None:
        number = number.strip()
        if not number:
            raise ValueError("Cart number cannot be blank.")
        if number in self.carts:
            raise ValueError(f"Cart #{number} already exists.")
        if category not in CATEGORY_COLORS:
            raise ValueError("Invalid cart colour.")
        self.carts[number] = Cart(number=number, category=category)
        self.reserve.append(number)
        try:
            self.move_cart(number, destination)
        except ValueError:
            self.reserve.remove(number)
            del self.carts[number]
            raise

    def delete_cart(self, number: str) -> None:
        if number not in self.carts:
            raise ValueError("Select a cart first.")
        cart = self.carts[number]
        if cart.team_id is not None:
            raise ValueError("You cannot delete a cart currently assigned to a team.")
        self.detach_cart(number)
        del self.carts[number]
        self.validate()

    def add_row(self) -> int:
        if self.row_count >= 12:
            raise ValueError("The maximum is 12 pit rows.")
        self.row_count += 1
        self.pit_rows[self.row_count] = []
        return self.row_count

    def remove_last_row(self) -> int:
        if self.row_count <= 1:
            raise ValueError("The session needs at least one pit row.")
        removed = self.row_count
        for number in self.pit_rows.pop(removed):
            self.carts[number].pit_row = None
            self.reserve.append(number)
        self.row_count -= 1
        self.validate()
        return removed

    def best_row(self) -> Optional[tuple[int, Cart]]:
        candidates: list[tuple[int, Cart]] = []
        for row, queue in self.pit_rows.items():
            if queue:
                candidates.append((row, self.carts[queue[0]]))
        good = [(row, cart) for row, cart in candidates if cart.category in GOOD_CATEGORIES]
        if not good:
            return None
        return min(
            good,
            key=lambda item: (
                math.inf if item[1].lap_time is None else item[1].lap_time,
                CATEGORY_PRIORITY[item[1].category],
                item[0],
            ),
        )

    def to_payload(self) -> dict:
        self.validate()
        return {
            "schema_version": SCHEMA_VERSION,
            "row_count": self.row_count,
            "teams": [asdict(team) for team in self.teams.values()],
            "carts": [asdict(cart) for cart in self.carts.values()],
            "pit_rows": {str(row): list(queue) for row, queue in self.pit_rows.items()},
            "reserve": list(self.reserve),
            "events": [asdict(event) for event in self.events],
        }

    @classmethod
    def from_payload(cls, payload: dict) -> SessionModel:
        if not isinstance(payload, dict):
            raise ValueError("The file does not contain a valid session.")
        if payload.get("schema_version") == SCHEMA_VERSION:
            return cls._from_current_payload(payload)
        if "cars" in payload and "pit_rows" in payload:
            return cls._from_legacy_payload(payload)
        raise ValueError("Unsupported session-file format.")

    @classmethod
    def _from_current_payload(cls, payload: dict) -> SessionModel:
        row_count = int(payload["row_count"])
        model = cls(row_count)
        for item in payload.get("carts", []):
            number = str(item["number"])
            category = str(item.get("category", "Blue"))
            if category not in CATEGORY_COLORS:
                category = "Blue"
            lap_time = item.get("lap_time")
            if lap_time is not None:
                lap_time = float(lap_time)
            model.carts[number] = Cart(number=number, category=category, lap_time=lap_time)

        for item in payload.get("teams", []):
            team_id = str(item["team_id"]).strip()
            cart_number = str(item["cart_number"])
            if not team_id or team_id in model.teams:
                raise ValueError("The file contains duplicate or blank team IDs.")
            if cart_number not in model.carts:
                raise ValueError(f"Team {team_id} references an unknown cart.")
            model.teams[team_id] = Team(team_id=team_id, cart_number=cart_number)
            model.carts[cart_number].team_id = team_id

        used = {team.cart_number for team in model.teams.values()}
        for row in range(1, row_count + 1):
            raw_queue = payload.get("pit_rows", {}).get(str(row), [])
            for raw_number in raw_queue:
                number = str(raw_number)
                if number not in model.carts or number in used:
                    continue
                used.add(number)
                model.pit_rows[row].append(number)
                model.carts[number].pit_row = row

        for raw_number in payload.get("reserve", []):
            number = str(raw_number)
            if number in model.carts and number not in used:
                used.add(number)
                model.reserve.append(number)
        for number in model.carts:
            if number not in used:
                model.reserve.append(number)

        for item in payload.get("events", []):
            try:
                model.events.append(
                    PitEvent(
                        sequence=int(item.get("sequence", len(model.events) + 1)),
                        timestamp=str(item.get("timestamp", "")),
                        team_id=str(item.get("team_id", "")),
                        row=int(item.get("row", 1)),
                        incoming_cart=str(item.get("incoming_cart", "")),
                        outgoing_cart=str(item.get("outgoing_cart", "")),
                    )
                )
            except (TypeError, ValueError):
                continue
        model.validate()
        return model

    @classmethod
    def _from_legacy_payload(cls, payload: dict) -> SessionModel:
        raw_rows = payload.get("pit_rows", {})
        row_numbers = [int(key) for key in raw_rows if str(key).isdigit()]
        model = cls(max(1, max(row_numbers, default=3)))
        for item in payload.get("cars", []):
            number = str(item["number"])
            category = str(item.get("category", "Blue"))
            if category not in CATEGORY_COLORS:
                category = "Blue"
            lap_time = item.get("lap_time")
            if lap_time is not None:
                lap_time = float(lap_time)
            model.carts[number] = Cart(number=number, category=category, lap_time=lap_time)

        waiting: set[str] = set()
        for row in range(1, model.row_count + 1):
            for raw_number in raw_rows.get(str(row), []):
                number = str(raw_number)
                if number in model.carts and number not in waiting:
                    waiting.add(number)
                    model.pit_rows[row].append(number)
                    model.carts[number].pit_row = row
        for number in sorted(set(model.carts) - waiting, key=natural_key):
            team_id = f"Team {number}"
            model.teams[team_id] = Team(team_id=team_id, cart_number=number)
            model.carts[number].team_id = team_id
        model.validate()
        return model


class EnduroPitManager(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1480x920")
        self.minsize(1180, 760)
        self.configure(bg="#15181d")

        self.session: Optional[SessionModel] = None
        self.selected_team_id: Optional[str] = None
        self.selected_cart_number: Optional[str] = None
        self._redraw_id: Optional[str] = None
        self._drawing = False
        self._drag_cart_number: Optional[str] = None
        self._drag_start_canvas = (0.0, 0.0)
        self._drag_last_canvas = (0.0, 0.0)
        self._drag_moved = False
        self._row_drop_zones: dict[int, tuple[float, float, float, float]] = {}
        self._reserve_drop_zone: Optional[tuple[float, float, float, float]] = None
        self._reserve_columns = 1
        self._reserve_top = 0.0
        self._undo_stack: list[dict] = []
        self.status_var = tk.StringVar(value="Create or load a session")

        self.style = ttk.Style(self)
        self._configure_style()
        self.show_setup_screen()

    def _configure_style(self) -> None:
        self.style.theme_use("clam")
        self.style.configure(
            "Treeview",
            background="#20252c",
            fieldbackground="#20252c",
            foreground="#f5f5f5",
            rowheight=30,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        self.style.map(
            "Treeview",
            background=[("selected", "#3b4a5d")],
            foreground=[("selected", "white")],
        )
        self.style.configure(
            "Treeview.Heading",
            background="#303740",
            foreground="white",
            relief="flat",
            font=("Segoe UI Semibold", 9),
        )
        self.style.configure("TNotebook", background="#15181d", borderwidth=0)
        self.style.configure(
            "TNotebook.Tab",
            background="#262d36",
            foreground="#c7cdd5",
            padding=(16, 8),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", "#3a4552")],
            foreground=[("selected", "white")],
        )
        self.style.configure("TCombobox", padding=5, font=("Segoe UI", 10))

    @staticmethod
    def button_style(background: str) -> dict:
        return {
            "bg": background,
            "fg": "white",
            "activebackground": background,
            "activeforeground": "white",
            "relief": "flat",
            "padx": 13,
            "pady": 7,
            "cursor": "hand2",
            "font": ("Segoe UI Semibold", 9),
        }

    def clear_window(self) -> None:
        self._drag_cart_number = None
        self._drag_moved = False
        if self._redraw_id is not None:
            try:
                self.after_cancel(self._redraw_id)
            except tk.TclError:
                pass
            self._redraw_id = None
        for child in self.winfo_children():
            child.destroy()

    def capture_undo_state(self) -> dict:
        session = self.require_session()
        return {
            "session": session.to_payload(),
            "selected_team_id": self.selected_team_id,
            "selected_cart_number": self.selected_cart_number,
        }

    def commit_undo_state(self, state: dict) -> None:
        if self.session is None or state["session"] == self.session.to_payload():
            return
        self._undo_stack.append(state)
        if len(self._undo_stack) > 100:
            del self._undo_stack[0]
        self.update_undo_button()

    def update_undo_button(self) -> None:
        if hasattr(self, "undo_button") and self.undo_button.winfo_exists():
            self.undo_button.config(
                state="normal" if self._undo_stack else "disabled"
            )

    def undo_last_action(self) -> None:
        if not self._undo_stack:
            self.status_var.set("Nothing to undo.")
            self.update_undo_button()
            return

        state = self._undo_stack.pop()
        self.session = SessionModel.from_payload(state["session"])
        selected_team = state["selected_team_id"]
        selected_cart = state["selected_cart_number"]
        self.selected_team_id = (
            selected_team if selected_team in self.session.teams else None
        )
        self.selected_cart_number = (
            selected_cart if selected_cart in self.session.carts else None
        )
        self.status_var.set("Last change undone.")
        self.update_undo_button()
        self.refresh_all()

    def show_setup_screen(self) -> None:
        self.clear_window()
        outer = tk.Frame(self, bg="#15181d")
        outer.pack(expand=True)
        card = tk.Frame(
            outer,
            bg="#232932",
            padx=50,
            pady=42,
            highlightbackground="#3a424d",
            highlightthickness=1,
        )
        card.pack()
        tk.Label(
            card,
            text="ENDURO TEAM & CART MANAGER",
            bg="#232932",
            fg="white",
            font=("Segoe UI Semibold", 24),
        ).pack(pady=(0, 8))
        tk.Label(
            card,
            text=(
                "Teams swap carts through FIFO pit rows: the first waiting cart "
                "leaves, and the incoming cart joins the back."
            ),
            wraplength=650,
            justify="center",
            bg="#232932",
            fg="#b8c0cb",
            font=("Segoe UI", 11),
        ).pack(pady=(0, 28))

        form = tk.Frame(card, bg="#232932")
        form.pack()
        self.setup_team_count = tk.IntVar(value=8)
        self.setup_cart_count = tk.IntVar(value=14)
        self.setup_row_count = tk.IntVar(value=3)
        fields = (
            ("Teams", self.setup_team_count, 1, 200),
            ("Carts", self.setup_cart_count, 2, 200),
            ("Pit rows", self.setup_row_count, 1, 12),
        )
        for column, (label, variable, minimum, maximum) in enumerate(fields):
            tk.Label(
                form,
                text=label,
                bg="#232932",
                fg="white",
                font=("Segoe UI Semibold", 10),
            ).grid(row=0, column=column, padx=14, pady=(0, 6))
            tk.Spinbox(
                form,
                from_=minimum,
                to=maximum,
                width=8,
                textvariable=variable,
                justify="center",
                bg="#15181d",
                fg="white",
                insertbackground="white",
                buttonbackground="#303740",
                relief="flat",
                font=("Segoe UI", 12),
            ).grid(row=1, column=column, padx=14, ipady=5)
        tk.Label(
            card,
            text="Carts must be at least: teams + pit rows.",
            bg="#232932",
            fg="#8f99a7",
            font=("Segoe UI", 9),
        ).pack(pady=(16, 4))

        tk.Label(
            card,
            text="Team names / IDs (optional)",
            bg="#232932",
            fg="white",
            font=("Segoe UI Semibold", 10),
        ).pack(anchor="w", pady=(12, 4))
        tk.Label(
            card,
            text=(
                "Enter names in team order, one per line or separated by commas. "
                "Leave this blank to use Team 1, Team 2, etc."
            ),
            wraplength=650,
            justify="left",
            bg="#232932",
            fg="#8f99a7",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 5))
        self.setup_team_names = tk.Text(
            card,
            height=4,
            width=62,
            bg="#15181d",
            fg="white",
            insertbackground="white",
            selectbackground="#3b4a5d",
            relief="flat",
            padx=8,
            pady=7,
            font=("Segoe UI", 10),
        )
        self.setup_team_names.pack(fill="x")

        buttons = tk.Frame(card, bg="#232932")
        buttons.pack(pady=(18, 0))
        tk.Button(
            buttons,
            text="CREATE SESSION",
            command=self.create_session,
            **self.button_style("#2d7d46"),
        ).pack(side="left", padx=6)
        tk.Button(
            buttons,
            text="LOAD SESSION",
            command=self.load_session,
            **self.button_style("#43576d"),
        ).pack(side="left", padx=6)

    def create_session(self) -> None:
        try:
            raw_names = self.setup_team_names.get("1.0", "end-1c")
            team_names = [
                name.strip()
                for name in raw_names.replace(",", "\n").splitlines()
            ]
            self.session = SessionModel.create(
                int(self.setup_team_count.get()),
                int(self.setup_cart_count.get()),
                int(self.setup_row_count.get()),
                team_names=team_names,
            )
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Cannot create session", str(exc))
            return
        self.selected_team_id = next(iter(self.session.teams), None)
        self.selected_cart_number = None
        self._undo_stack.clear()
        self.status_var.set("New session created")
        self.build_main_ui()

    def build_main_ui(self) -> None:
        if self.session is None:
            return
        self.clear_window()
        topbar = tk.Frame(self, bg="#101318", height=58)
        topbar.pack(fill="x")
        tk.Label(
            topbar,
            text="ENDURO TEAM & CART MANAGER",
            bg="#101318",
            fg="white",
            font=("Segoe UI Semibold", 16),
        ).pack(side="left", padx=18, pady=14)
        for text, command, colour in (
            ("NEW", self.confirm_new_session, "#5a3942"),
            ("LOAD", self.load_session, "#43576d"),
            ("UNDO", self.undo_last_action, "#4b5d70"),
            ("SAVE", self.save_session, "#2d7d46"),
        ):
            button = tk.Button(
                topbar,
                text=text,
                command=command,
                **self.button_style(colour),
            )
            button.pack(side="right", padx=(0, 8), pady=10)
            if text == "UNDO":
                self.undo_button = button
        self.update_undo_button()

        body = tk.PanedWindow(
            self,
            orient="horizontal",
            bg="#15181d",
            sashwidth=7,
            sashrelief="flat",
            borderwidth=0,
        )
        body.pack(fill="both", expand=True, padx=12, pady=12)
        self.left_panel = tk.Frame(body, bg="#1b2027", width=565)
        self.right_panel = tk.Frame(body, bg="#1b2027")
        body.add(self.left_panel, minsize=480)
        body.add(self.right_panel, minsize=580)

        self.notebook = ttk.Notebook(self.left_panel)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self.team_tab = tk.Frame(self.notebook, bg="#1b2027")
        self.cart_tab = tk.Frame(self.notebook, bg="#1b2027")
        self.log_tab = tk.Frame(self.notebook, bg="#1b2027")
        self.notebook.add(self.team_tab, text="TEAMS")
        self.notebook.add(self.cart_tab, text="CARTS")
        self.notebook.add(self.log_tab, text="PIT LOG")
        self.build_team_tab()
        self.build_cart_tab()
        self.build_log_tab()
        self.build_pit_panel()

        tk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            bg="#101318",
            fg="#b7c0cb",
            padx=14,
            pady=6,
            font=("Segoe UI", 9),
        ).pack(fill="x")
        self.refresh_all()

    def build_team_tab(self) -> None:
        toolbar = tk.Frame(self.team_tab, bg="#1b2027")
        toolbar.pack(fill="x", pady=(2, 8))
        tk.Button(
            toolbar,
            text="+ ADD TEAM",
            command=self.open_add_team_dialog,
            **self.button_style("#355f7a"),
        ).pack(side="left")
        tk.Button(
            toolbar,
            text="DELETE TEAM",
            command=self.delete_selected_team,
            **self.button_style("#713d46"),
        ).pack(side="left", padx=6)

        tree_frame = tk.Frame(self.team_tab, bg="#1b2027")
        tree_frame.pack(fill="both", expand=True)
        columns = ("team", "cart", "colour", "lap")
        self.team_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {"team": "TEAM ID", "cart": "CART", "colour": "COLOUR", "lap": "BEST LAP"}
        widths = {"team": 165, "cart": 65, "colour": 85, "lap": 95}
        for column in columns:
            self.team_tree.heading(column, text=headings[column])
            self.team_tree.column(column, width=widths[column], anchor="center")
        self.team_tree.column("team", anchor="w")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.team_tree.yview)
        self.team_tree.configure(yscrollcommand=scroll.set)
        self.team_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.team_tree.bind("<<TreeviewSelect>>", self.on_team_select)

        editor = tk.Frame(
            self.team_tab,
            bg="#242b34",
            padx=12,
            pady=12,
            highlightbackground="#38434f",
            highlightthickness=1,
        )
        editor.pack(fill="x", pady=(10, 8))
        tk.Label(
            editor,
            text="SELECTED TEAM",
            bg="#242b34",
            fg="#aeb7c2",
            font=("Segoe UI Semibold", 9),
        ).grid(row=0, column=0, sticky="w")
        self.team_id_var = tk.StringVar()
        self.team_id_entry = tk.Entry(
            editor,
            textvariable=self.team_id_var,
            bg="#15181d",
            fg="white",
            insertbackground="white",
            relief="flat",
            font=("Segoe UI", 11),
        )
        self.team_id_entry.grid(row=1, column=0, sticky="ew", ipady=6, pady=(4, 8))
        tk.Button(
            editor,
            text="RENAME",
            command=self.rename_selected_team,
            **self.button_style("#4b5d70"),
        ).grid(row=1, column=1, padx=(8, 0), pady=(4, 8))
        self.team_cart_label = tk.Label(
            editor,
            text="Current cart: —",
            bg="#242b34",
            fg="white",
            font=("Segoe UI Semibold", 11),
        )
        self.team_cart_label.grid(row=2, column=0, columnspan=2, sticky="w")
        editor.grid_columnconfigure(0, weight=1)
        tk.Label(
            self.team_tab,
            text="PIT & SWAP CART",
            bg="#1b2027",
            fg="#b8c0cb",
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", pady=(4, 5))
        self.team_pit_buttons = tk.Frame(self.team_tab, bg="#1b2027")
        self.team_pit_buttons.pack(fill="x")

    def build_cart_tab(self) -> None:
        toolbar = tk.Frame(self.cart_tab, bg="#1b2027")
        toolbar.pack(fill="x", pady=(2, 8))
        tk.Button(
            toolbar,
            text="+ ADD CART",
            command=self.open_add_cart_dialog,
            **self.button_style("#355f7a"),
        ).pack(side="left")
        tk.Button(
            toolbar,
            text="DELETE CART",
            command=self.delete_selected_cart,
            **self.button_style("#713d46"),
        ).pack(side="left", padx=6)

        tree_frame = tk.Frame(self.cart_tab, bg="#1b2027")
        tree_frame.pack(fill="both", expand=True)
        columns = ("cart", "colour", "lap", "location")
        self.cart_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {"cart": "CART", "colour": "COLOUR", "lap": "BEST LAP", "location": "LOCATION"}
        widths = {"cart": 65, "colour": 80, "lap": 95, "location": 200}
        for column in columns:
            self.cart_tree.heading(column, text=headings[column])
            self.cart_tree.column(column, width=widths[column], anchor="center")
        self.cart_tree.column("location", anchor="w")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.cart_tree.yview)
        self.cart_tree.configure(yscrollcommand=scroll.set)
        self.cart_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.cart_tree.bind("<<TreeviewSelect>>", self.on_cart_select)

        editor = tk.Frame(
            self.cart_tab,
            bg="#242b34",
            padx=12,
            pady=12,
            highlightbackground="#38434f",
            highlightthickness=1,
        )
        editor.pack(fill="x", pady=(10, 0))
        self.cart_editor_title = tk.Label(
            editor,
            text="SELECT A CART",
            bg="#242b34",
            fg="white",
            font=("Segoe UI Semibold", 11),
        )
        self.cart_editor_title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.cart_colour_var = tk.StringVar(value="Blue")
        self.cart_lap_var = tk.StringVar()
        self.cart_location_var = tk.StringVar(value="Reserve")
        for column, label in enumerate(("Colour", "Best lap", "Location")):
            tk.Label(
                editor,
                text=label,
                bg="#242b34",
                fg="#aeb7c2",
                font=("Segoe UI", 9),
            ).grid(row=1, column=column, sticky="w")
        self.cart_colour_combo = ttk.Combobox(
            editor,
            textvariable=self.cart_colour_var,
            values=list(CATEGORY_COLORS),
            state="readonly",
            width=12,
        )
        self.cart_colour_combo.grid(row=2, column=0, sticky="ew", padx=(0, 7))
        tk.Entry(
            editor,
            textvariable=self.cart_lap_var,
            bg="#15181d",
            fg="white",
            insertbackground="white",
            relief="flat",
            font=("Segoe UI", 10),
        ).grid(row=2, column=1, sticky="ew", padx=(0, 7), ipady=6)
        self.cart_location_combo = ttk.Combobox(
            editor,
            textvariable=self.cart_location_var,
            state="readonly",
            width=20,
        )
        self.cart_location_combo.grid(row=2, column=2, sticky="ew")
        tk.Button(
            editor,
            text="SAVE CART",
            command=self.update_selected_cart,
            **self.button_style("#2d7d46"),
        ).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        for column in range(3):
            editor.grid_columnconfigure(column, weight=1)

    def build_log_tab(self) -> None:
        columns = ("number", "time", "team", "row", "swap")
        self.log_tree = ttk.Treeview(
            self.log_tab,
            columns=columns,
            show="headings",
            selectmode="none",
        )
        headings = {"number": "#", "time": "TIME", "team": "TEAM", "row": "ROW", "swap": "CART SWAP"}
        widths = {"number": 40, "time": 70, "team": 145, "row": 50, "swap": 150}
        for column in columns:
            self.log_tree.heading(column, text=headings[column])
            self.log_tree.column(column, width=widths[column], anchor="center")
        self.log_tree.column("team", anchor="w")
        scroll = ttk.Scrollbar(self.log_tab, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=scroll.set)
        self.log_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def build_pit_panel(self) -> None:
        header = tk.Frame(self.right_panel, bg="#1b2027")
        header.pack(fill="x", padx=12, pady=(12, 8))
        tk.Label(
            header,
            text="PIT ROWS",
            bg="#1b2027",
            fg="white",
            font=("Segoe UI Semibold", 16),
        ).pack(side="left")
        tk.Button(
            header,
            text="− REMOVE LAST ROW",
            command=self.remove_last_row,
            **self.button_style("#713d46"),
        ).pack(side="right", padx=(6, 0))
        tk.Button(
            header,
            text="+ ADD ROW",
            command=self.add_row,
            **self.button_style("#355f7a"),
        ).pack(side="right")

        self.recommendation_box = tk.Frame(
            self.right_panel,
            bg="#5b3541",
            padx=14,
            pady=10,
            highlightbackground="#72505b",
            highlightthickness=1,
        )
        self.recommendation_box.pack(fill="x", padx=12, pady=(0, 8))
        self.recommendation_label = tk.Label(
            self.recommendation_box,
            text="WAIT",
            bg="#5b3541",
            fg="white",
            font=("Segoe UI Semibold", 13),
        )
        self.recommendation_label.pack(side="left")
        self.recommendation_detail = tk.Label(
            self.recommendation_box,
            text="No suitable front cart",
            bg="#5b3541",
            fg="#f0dfe3",
            font=("Segoe UI", 9),
        )
        self.recommendation_detail.pack(side="left", padx=(16, 0))

        tk.Label(
            self.right_panel,
            text=(
                "Drag waiting carts to reorder them or move them between pit rows "
                "and Reserve."
            ),
            anchor="w",
            bg="#1b2027",
            fg="#8f99a7",
            font=("Segoe UI", 9),
        ).pack(fill="x", padx=14, pady=(0, 6))

        canvas_frame = tk.Frame(self.right_panel, bg="#11151a")
        canvas_frame.pack(fill="both", expand=True, padx=12)
        self.pit_canvas = tk.Canvas(canvas_frame, bg="#11151a", highlightthickness=0)
        xscroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.pit_canvas.xview)
        yscroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.pit_canvas.yview)
        self.pit_canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.pit_canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
        self.pit_canvas.bind("<Configure>", lambda _event: self.request_redraw())
        self.pit_canvas.bind("<MouseWheel>", self.on_canvas_mousewheel)
        self.pit_canvas.bind("<B1-Motion>", self.on_cart_drag_motion)
        self.pit_canvas.bind("<ButtonRelease-1>", self.on_cart_drag_release)

    def on_canvas_mousewheel(self, event) -> None:
        self.pit_canvas.yview_scroll(int(-event.delta / 120), "units")

    def refresh_all(self) -> None:
        if self.session is None or not hasattr(self, "team_tree"):
            return
        self.refresh_team_tree()
        self.refresh_cart_tree()
        self.refresh_log()
        self.refresh_team_editor()
        self.refresh_cart_editor()
        self.rebuild_pit_buttons()
        self.update_recommendation()
        self.request_redraw()

    def refresh_team_tree(self) -> None:
        session = self.require_session()
        for item in self.team_tree.get_children():
            self.team_tree.delete(item)
        for team_id in sorted(session.teams, key=natural_key):
            team = session.teams[team_id]
            cart = session.carts[team.cart_number]
            self.team_tree.insert(
                "",
                "end",
                iid=team_id,
                values=(team_id, f"#{cart.number}", cart.category, format_time(cart.lap_time)),
            )
        if self.selected_team_id in session.teams:
            self.team_tree.selection_set(self.selected_team_id)
            self.team_tree.focus(self.selected_team_id)
            self.team_tree.see(self.selected_team_id)
        elif session.teams:
            self.selected_team_id = next(iter(session.teams))
            self.team_tree.selection_set(self.selected_team_id)

    def refresh_cart_tree(self) -> None:
        session = self.require_session()
        for item in self.cart_tree.get_children():
            self.cart_tree.delete(item)
        for number in sorted(session.carts, key=natural_key):
            cart = session.carts[number]
            self.cart_tree.insert(
                "",
                "end",
                iid=number,
                values=(
                    f"#{number}",
                    cart.category,
                    format_time(cart.lap_time),
                    session.cart_location(number),
                ),
            )
        if self.selected_cart_number in session.carts:
            self.cart_tree.selection_set(self.selected_cart_number)
            self.cart_tree.focus(self.selected_cart_number)
            self.cart_tree.see(self.selected_cart_number)

    def refresh_log(self) -> None:
        session = self.require_session()
        for item in self.log_tree.get_children():
            self.log_tree.delete(item)
        for event in reversed(session.events):
            self.log_tree.insert(
                "",
                "end",
                values=(
                    event.sequence,
                    event.timestamp,
                    event.team_id,
                    event.row,
                    f"#{event.incoming_cart} → #{event.outgoing_cart}",
                ),
            )

    def on_team_select(self, _event=None) -> None:
        selected = self.team_tree.selection()
        if not selected:
            return
        self.selected_team_id = selected[0]
        self.refresh_team_editor()
        self.update_recommendation()
        self.request_redraw()

    def refresh_team_editor(self) -> None:
        if not hasattr(self, "team_id_var"):
            return
        session = self.require_session()
        if self.selected_team_id not in session.teams:
            self.team_id_var.set("")
            self.team_cart_label.config(text="Current cart: —")
            return
        team = session.teams[self.selected_team_id]
        cart = session.carts[team.cart_number]
        self.team_id_var.set(team.team_id)
        self.team_cart_label.config(
            text=(
                f"Current cart: #{cart.number}  •  {cart.category}  •  "
                f"best lap {format_time(cart.lap_time)}"
            )
        )

    def on_cart_select(self, _event=None) -> None:
        selected = self.cart_tree.selection()
        if not selected:
            return
        self.selected_cart_number = selected[0]
        self.refresh_cart_editor()
        self.request_redraw()

    def refresh_cart_editor(self) -> None:
        if not hasattr(self, "cart_editor_title"):
            return
        session = self.require_session()
        if self.selected_cart_number not in session.carts:
            self.cart_editor_title.config(text="SELECT A CART")
            self.cart_lap_var.set("")
            return
        cart = session.carts[self.selected_cart_number]
        self.cart_editor_title.config(text=f"CART #{cart.number}")
        self.cart_colour_var.set(cart.category)
        self.cart_lap_var.set("" if cart.lap_time is None else format_time(cart.lap_time))
        if cart.team_id is not None:
            values = [f"Racing — {cart.team_id}"]
            self.cart_location_var.set(values[0])
        else:
            values = ["Reserve"] + [f"Row {row}" for row in range(1, session.row_count + 1)]
            self.cart_location_var.set(
                "Reserve" if cart.pit_row is None else f"Row {cart.pit_row}"
            )
        self.cart_location_combo.configure(values=values)

    def rebuild_pit_buttons(self) -> None:
        session = self.require_session()
        for child in self.team_pit_buttons.winfo_children():
            child.destroy()
        for row in range(1, session.row_count + 1):
            queue = session.pit_rows[row]
            front = f"#{queue[0]}" if queue else "EMPTY"
            tk.Button(
                self.team_pit_buttons,
                text=f"ROW {row}\nfront {front}",
                command=lambda selected_row=row: self.pit_selected_team(selected_row),
                **self.button_style("#8a5a2b" if queue else "#4b4f55"),
            ).grid(
                row=(row - 1) // 3,
                column=(row - 1) % 3,
                sticky="ew",
                padx=3,
                pady=3,
            )
        for column in range(3):
            self.team_pit_buttons.grid_columnconfigure(column, weight=1)

    def update_recommendation(self) -> None:
        session = self.require_session()
        best = session.best_row()
        if best is None:
            fronts = []
            for row, queue in session.pit_rows.items():
                if not queue:
                    fronts.append(f"R{row} empty")
                else:
                    cart = session.carts[queue[0]]
                    fronts.append(f"R{row} #{cart.number} {cart.category}")
            self.recommendation_box.config(bg="#5b3541", highlightbackground="#72505b")
            self.recommendation_label.config(text="WAIT", bg="#5b3541")
            self.recommendation_detail.config(
                text=" • ".join(fronts) if fronts else "No waiting carts",
                bg="#5b3541",
                fg="#f0dfe3",
            )
            return
        row, cart = best
        team_text = f"{self.selected_team_id}: " if self.selected_team_id in session.teams else ""
        self.recommendation_box.config(bg="#235f3a", highlightbackground="#3a8b59")
        self.recommendation_label.config(text="BEST TIME TO PIT", bg="#235f3a")
        self.recommendation_detail.config(
            text=(
                f"{team_text}Row {row} → Cart #{cart.number}, {cart.category}, "
                f"best lap {format_time(cart.lap_time)}"
            ),
            bg="#235f3a",
            fg="#dff3e6",
        )

    def pit_selected_team(self, row: int) -> None:
        session = self.require_session()
        if self.selected_team_id not in session.teams:
            messagebox.showinfo("No team", "Select a team first.")
            return
        undo_state = self.capture_undo_state()
        try:
            event = session.pit_exchange(self.selected_team_id, row)
        except ValueError as exc:
            messagebox.showerror("Pit exchange unavailable", str(exc))
            return
        self.commit_undo_state(undo_state)
        self.selected_cart_number = event.outgoing_cart
        self.status_var.set(
            f"{event.team_id} parked Cart #{event.incoming_cart} in Row {row} "
            f"and left in Cart #{event.outgoing_cart}."
        )
        self.refresh_all()

    def rename_selected_team(self) -> None:
        session = self.require_session()
        if self.selected_team_id not in session.teams:
            messagebox.showinfo("No team", "Select a team first.")
            return
        old_id = self.selected_team_id
        new_id = self.team_id_var.get()
        undo_state = self.capture_undo_state()
        try:
            session.rename_team(old_id, new_id)
        except ValueError as exc:
            messagebox.showerror("Cannot rename team", str(exc))
            return
        self.commit_undo_state(undo_state)
        self.selected_team_id = new_id.strip()
        self.status_var.set(f"Team renamed to {self.selected_team_id}.")
        self.refresh_all()

    def open_add_team_dialog(self) -> None:
        session = self.require_session()
        if not session.reserve:
            messagebox.showinfo(
                "No reserve cart",
                "Move a parked cart to Reserve before adding another team.",
            )
            return
        dialog = tk.Toplevel(self)
        dialog.title("Add team")
        dialog.geometry("390x245")
        dialog.resizable(False, False)
        dialog.configure(bg="#232932")
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(
            dialog,
            text="ADD TEAM",
            bg="#232932",
            fg="white",
            font=("Segoe UI Semibold", 16),
        ).pack(pady=(20, 14))
        form = tk.Frame(dialog, bg="#232932")
        form.pack(fill="x", padx=28)
        team_var = tk.StringVar()
        cart_var = tk.StringVar(value=session.reserve[0])
        tk.Label(form, text="Team ID / name", bg="#232932", fg="#c5ccd5").pack(anchor="w")
        entry = tk.Entry(
            form,
            textvariable=team_var,
            bg="#15181d",
            fg="white",
            insertbackground="white",
            relief="flat",
        )
        entry.pack(fill="x", ipady=6, pady=(3, 10))
        tk.Label(form, text="Starting reserve cart", bg="#232932", fg="#c5ccd5").pack(anchor="w")
        ttk.Combobox(
            form,
            textvariable=cart_var,
            values=session.reserve,
            state="readonly",
        ).pack(fill="x", pady=(3, 12))

        def add() -> None:
            undo_state = self.capture_undo_state()
            try:
                session.add_team(team_var.get(), cart_var.get())
            except ValueError as exc:
                messagebox.showerror("Cannot add team", str(exc), parent=dialog)
                return
            self.commit_undo_state(undo_state)
            self.selected_team_id = team_var.get().strip()
            dialog.destroy()
            self.status_var.set(f"Added {self.selected_team_id}.")
            self.refresh_all()

        tk.Button(dialog, text="ADD TEAM", command=add, **self.button_style("#2d7d46")).pack()
        entry.focus_set()
        dialog.bind("<Return>", lambda _event: add())

    def delete_selected_team(self) -> None:
        session = self.require_session()
        team_id = self.selected_team_id
        if team_id not in session.teams:
            messagebox.showinfo("No team", "Select a team first.")
            return
        if not messagebox.askyesno(
            "Delete team",
            f"Delete {team_id}? Its current cart will move to Reserve.",
        ):
            return
        undo_state = self.capture_undo_state()
        session.delete_team(team_id)
        self.commit_undo_state(undo_state)
        self.selected_team_id = next(iter(session.teams), None)
        self.status_var.set(f"Deleted {team_id}.")
        self.refresh_all()

    def update_selected_cart(self) -> None:
        session = self.require_session()
        number = self.selected_cart_number
        if number not in session.carts:
            messagebox.showinfo("No cart", "Select a cart first.")
            return
        undo_state = self.capture_undo_state()
        try:
            lap_time = parse_time(self.cart_lap_var.get())
            category = self.cart_colour_var.get()
            if category not in CATEGORY_COLORS:
                raise ValueError("Choose a valid cart colour.")
            cart = session.carts[number]
            cart.category = category
            cart.lap_time = lap_time
            if cart.team_id is None:
                desired_location = self.cart_location_var.get()
                current_location = (
                    "Reserve" if cart.pit_row is None else f"Row {cart.pit_row}"
                )
                if desired_location != current_location:
                    session.move_cart(number, desired_location)
            session.validate()
        except ValueError as exc:
            messagebox.showerror("Cannot update cart", str(exc))
            return
        self.commit_undo_state(undo_state)
        self.status_var.set(f"Updated Cart #{number}.")
        self.refresh_all()

    def open_add_cart_dialog(self) -> None:
        session = self.require_session()
        dialog = tk.Toplevel(self)
        dialog.title("Add cart")
        dialog.geometry("390x300")
        dialog.resizable(False, False)
        dialog.configure(bg="#232932")
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(
            dialog,
            text="ADD CART",
            bg="#232932",
            fg="white",
            font=("Segoe UI Semibold", 16),
        ).pack(pady=(20, 14))
        form = tk.Frame(dialog, bg="#232932")
        form.pack(fill="x", padx=28)
        number_var = tk.StringVar()
        colour_var = tk.StringVar(value="Blue")
        location_var = tk.StringVar(value="Reserve")
        values = ["Reserve"] + [f"Row {row}" for row in range(1, session.row_count + 1)]
        for label, variable, widget_type, options in (
            ("Cart number", number_var, "entry", None),
            ("Colour", colour_var, "combo", list(CATEGORY_COLORS)),
            ("Starting location", location_var, "combo", values),
        ):
            tk.Label(form, text=label, bg="#232932", fg="#c5ccd5").pack(anchor="w")
            if widget_type == "entry":
                tk.Entry(
                    form,
                    textvariable=variable,
                    bg="#15181d",
                    fg="white",
                    insertbackground="white",
                    relief="flat",
                ).pack(fill="x", ipady=6, pady=(3, 9))
            else:
                ttk.Combobox(
                    form,
                    textvariable=variable,
                    values=options,
                    state="readonly",
                ).pack(fill="x", pady=(3, 9))

        def add() -> None:
            undo_state = self.capture_undo_state()
            try:
                session.add_cart(number_var.get(), colour_var.get(), location_var.get())
            except ValueError as exc:
                messagebox.showerror("Cannot add cart", str(exc), parent=dialog)
                return
            self.commit_undo_state(undo_state)
            self.selected_cart_number = number_var.get().strip()
            dialog.destroy()
            self.status_var.set(f"Added Cart #{self.selected_cart_number}.")
            self.refresh_all()

        tk.Button(dialog, text="ADD CART", command=add, **self.button_style("#2d7d46")).pack(pady=(5, 0))

    def delete_selected_cart(self) -> None:
        session = self.require_session()
        number = self.selected_cart_number
        if number not in session.carts:
            messagebox.showinfo("No cart", "Select a cart first.")
            return
        if not messagebox.askyesno("Delete cart", f"Delete Cart #{number}?"):
            return
        undo_state = self.capture_undo_state()
        try:
            session.delete_cart(number)
        except ValueError as exc:
            messagebox.showerror("Cannot delete cart", str(exc))
            return
        self.commit_undo_state(undo_state)
        self.selected_cart_number = None
        self.status_var.set(f"Deleted Cart #{number}.")
        self.refresh_all()

    def add_row(self) -> None:
        session = self.require_session()
        undo_state = self.capture_undo_state()
        try:
            row = session.add_row()
        except ValueError as exc:
            messagebox.showerror("Cannot add row", str(exc))
            return
        self.commit_undo_state(undo_state)
        self.status_var.set(f"Added Row {row}. Move a reserve or parked cart into it before use.")
        self.refresh_all()

    def remove_last_row(self) -> None:
        session = self.require_session()
        if not messagebox.askyesno(
            "Remove last row",
            f"Remove Row {session.row_count}? Its carts will move to Reserve.",
        ):
            return
        undo_state = self.capture_undo_state()
        try:
            removed = session.remove_last_row()
        except ValueError as exc:
            messagebox.showerror("Cannot remove row", str(exc))
            return
        self.commit_undo_state(undo_state)
        self.status_var.set(f"Removed Row {removed}; its carts are now in Reserve.")
        self.refresh_all()

    def request_redraw(self) -> None:
        if not hasattr(self, "pit_canvas") or not self.pit_canvas.winfo_exists():
            return
        if self._redraw_id is not None:
            try:
                self.after_cancel(self._redraw_id)
            except tk.TclError:
                pass
        self._redraw_id = self.after_idle(self.draw_pitlane)

    def draw_pitlane(self) -> None:
        self._redraw_id = None
        if self._drawing or not hasattr(self, "pit_canvas"):
            return
        self._drawing = True
        try:
            self._draw_pitlane_now()
        finally:
            self._drawing = False

    def _draw_pitlane_now(self) -> None:
        session = self.require_session()
        canvas = self.pit_canvas
        canvas.delete("all")
        lane_width = 190
        lane_gap = 18
        margin_x = 28
        max_queue = max((len(queue) for queue in session.pit_rows.values()), default=0)
        row_body_height = max(400, 115 + max_queue * 94)
        total_width = max(
            canvas.winfo_width(),
            margin_x * 2 + session.row_count * lane_width + (session.row_count - 1) * lane_gap,
        )
        reserve_rows = math.ceil(max(1, len(session.reserve)) / max(1, session.row_count * 2))
        total_height = max(canvas.winfo_height(), row_body_height + 135 + reserve_rows * 76)
        canvas.configure(scrollregion=(0, 0, total_width, total_height))
        self._row_drop_zones = {}
        self._reserve_drop_zone = None
        canvas.create_text(
            total_width / 2,
            20,
            text="PIT EXIT / FRONT CART LEAVES",
            fill="#dfe5ec",
            font=("Segoe UI Semibold", 10),
        )
        canvas.create_line(
            total_width / 2,
            35,
            total_width / 2,
            49,
            fill="#dfe5ec",
            width=2,
            arrow=tk.FIRST,
        )
        for row in range(1, session.row_count + 1):
            left = margin_x + (row - 1) * (lane_width + lane_gap)
            right = left + lane_width
            center = (left + right) / 2
            self._row_drop_zones[row] = (left, 55, right, row_body_height)
            canvas.create_rectangle(
                left,
                55,
                right,
                row_body_height,
                fill="#171c22",
                outline="#3b4653",
                width=2,
            )
            canvas.create_rectangle(left, 55, right, 87, fill="#303844", outline="")
            queue = session.pit_rows[row]
            canvas.create_text(
                center,
                71,
                text=f"ROW {row}  •  {len(queue)} CART{'S' if len(queue) != 1 else ''}",
                fill="white",
                font=("Segoe UI Semibold", 10),
            )
            if not queue:
                canvas.create_text(
                    center,
                    130,
                    text="EMPTY\nMove a cart here",
                    justify="center",
                    fill="#68727e",
                    font=("Segoe UI Semibold", 10),
                )
                continue
            for index, number in enumerate(queue):
                cart = session.carts[number]
                top = 103 + index * 94
                self.draw_cart(
                    canvas,
                    center - 57,
                    top,
                    center + 57,
                    top + 67,
                    cart,
                    front=(index == 0),
                    selected=(number == self.selected_cart_number),
                )
                canvas.create_text(
                    center,
                    top + 78,
                    text=("FRONT / NEXT OUT" if index == 0 else f"QUEUE POSITION {index + 1}"),
                    fill="#77ff9d" if index == 0 else "#77818d",
                    font=("Segoe UI Semibold", 7),
                )

        reserve_top = row_body_height + 30
        self._reserve_top = reserve_top
        self._reserve_drop_zone = (
            20,
            reserve_top,
            total_width - 20,
            total_height,
        )
        canvas.create_line(20, reserve_top, total_width - 20, reserve_top, fill="#343d48")
        canvas.create_text(
            30,
            reserve_top + 22,
            text=f"RESERVE CARTS ({len(session.reserve)})",
            anchor="w",
            fill="#aab3be",
            font=("Segoe UI Semibold", 10),
        )
        columns = max(1, int((total_width - 60) // 135))
        self._reserve_columns = columns
        for index, number in enumerate(session.reserve):
            cart = session.carts[number]
            column = index % columns
            row_index = index // columns
            left = 30 + column * 135
            top = reserve_top + 45 + row_index * 76
            self.draw_cart(
                canvas,
                left,
                top,
                left + 105,
                top + 58,
                cart,
                front=False,
                selected=(number == self.selected_cart_number),
            )
        canvas.tag_bind("cart", "<ButtonPress-1>", self.on_cart_drag_start)

    def draw_cart(
        self,
        canvas: tk.Canvas,
        left: float,
        top: float,
        right: float,
        bottom: float,
        cart: Cart,
        front: bool,
        selected: bool,
    ) -> None:
        fill = CATEGORY_COLORS[cart.category]
        text_fill = TEXT_COLORS[cart.category]
        outline = "#ffffff" if selected else ("#77ff9d" if front else "#111111")
        width = 4 if selected else (3 if front else 1)
        tag = ("cart", f"cart:{cart.number}")
        wheel_width = max(4, (right - left) * 0.07)
        wheel_height = max(8, (bottom - top) * 0.23)
        for x1, x2 in ((left - wheel_width, left + 1), (right - 1, right + wheel_width)):
            canvas.create_rectangle(
                x1,
                top + 6,
                x2,
                top + 6 + wheel_height,
                fill="#050505",
                outline="",
                tags=tag,
            )
            canvas.create_rectangle(
                x1,
                bottom - 6 - wheel_height,
                x2,
                bottom - 6,
                fill="#050505",
                outline="",
                tags=tag,
            )
        canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=fill,
            outline=outline,
            width=width,
            tags=tag,
        )
        roof_x = (right - left) * 0.17
        roof_y = (bottom - top) * 0.19
        canvas.create_rectangle(
            left + roof_x,
            top + roof_y,
            right - roof_x,
            bottom - roof_y,
            fill="#d9e1e8",
            stipple="gray50",
            outline="",
            tags=tag,
        )
        canvas.create_polygon(
            left + roof_x,
            top + roof_y,
            right - roof_x,
            top + roof_y,
            right - roof_x * 1.25,
            top + roof_y * 1.65,
            left + roof_x * 1.25,
            top + roof_y * 1.65,
            fill="#1f2d38",
            outline="",
            tags=tag,
        )
        canvas.create_text(
            (left + right) / 2,
            (top + bottom) / 2 - 3,
            text=f"#{cart.number}",
            fill=text_fill,
            font=("Segoe UI Black", 11),
            tags=tag,
        )
        canvas.create_text(
            (left + right) / 2,
            bottom - 8,
            text=f"{cart.category}  {format_time(cart.lap_time)}",
            fill=text_fill,
            font=("Segoe UI", 7),
            tags=tag,
        )

    def on_cart_drag_start(self, event) -> None:
        current = self.pit_canvas.find_withtag("current")
        if not current:
            return
        number = None
        for tag in self.pit_canvas.gettags(current[0]):
            if tag.startswith("cart:"):
                number = tag.split(":", 1)[1]
                break
        if number is None:
            return

        self.selected_cart_number = number
        x = self.pit_canvas.canvasx(event.x)
        y = self.pit_canvas.canvasy(event.y)
        self._drag_cart_number = number
        self._drag_start_canvas = (x, y)
        self._drag_last_canvas = (x, y)
        self._drag_moved = False
        self.pit_canvas.configure(cursor="fleur")
        self.pit_canvas.tag_raise(f"cart:{number}")

    def on_cart_drag_motion(self, event) -> None:
        number = self._drag_cart_number
        if number is None:
            return
        x = self.pit_canvas.canvasx(event.x)
        y = self.pit_canvas.canvasy(event.y)
        last_x, last_y = self._drag_last_canvas
        start_x, start_y = self._drag_start_canvas
        if abs(x - start_x) > 4 or abs(y - start_y) > 4:
            self._drag_moved = True
        self.pit_canvas.move(f"cart:{number}", x - last_x, y - last_y)
        self._drag_last_canvas = (x, y)

    def on_cart_drag_release(self, event) -> None:
        number = self._drag_cart_number
        if number is None:
            return

        self._drag_cart_number = None
        self.pit_canvas.configure(cursor="")
        session = self.require_session()

        if not self._drag_moved:
            self.notebook.select(self.cart_tab)
            self.refresh_cart_tree()
            self.refresh_cart_editor()
            self.request_redraw()
            return

        bbox = self.pit_canvas.bbox(f"cart:{number}")
        if bbox is None:
            self.request_redraw()
            return
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2

        destination: Optional[str] = None
        insertion_index: Optional[int] = None
        for row, (left, top, right, bottom) in self._row_drop_zones.items():
            if left <= center_x <= right and top <= center_y <= bottom:
                destination = f"Row {row}"
                insertion_index = max(
                    0,
                    int(math.floor((center_y - 136.5) / 94 + 0.5)),
                )
                break

        if destination is None and self._reserve_drop_zone is not None:
            left, top, right, bottom = self._reserve_drop_zone
            if left <= center_x <= right and top <= center_y <= bottom:
                destination = "Reserve"
                column = max(0, int((center_x - 30) // 135))
                column = min(column, self._reserve_columns - 1)
                reserve_row = max(0, int((center_y - (self._reserve_top + 45)) // 76))
                insertion_index = reserve_row * self._reserve_columns + column

        if destination is None:
            self.status_var.set(
                f"Cart #{number} was returned to its original position."
            )
            self.refresh_all()
            return

        old_location = session.cart_location(number)
        undo_state = self.capture_undo_state()
        try:
            session.place_cart(number, destination, insertion_index)
        except ValueError as exc:
            messagebox.showerror("Cannot move cart", str(exc))
            self.refresh_all()
            return
        self.commit_undo_state(undo_state)

        new_location = session.cart_location(number)
        self.status_var.set(
            f"Moved Cart #{number}: {old_location} → {new_location}."
        )
        self.refresh_all()

    def save_session(self) -> None:
        session = self.require_session()
        path = filedialog.asksaveasfilename(
            title="Save enduro session",
            defaultextension=".json",
            filetypes=[("Enduro session", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(session.to_payload(), file, indent=2)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Save failed", f"Could not save this session.\n\n{exc}")
            return
        self.status_var.set(f"Session saved to {path}")
        messagebox.showinfo("Saved", "The enduro session was saved.")

    def load_session(self) -> None:
        path = filedialog.askopenfilename(
            title="Load enduro session",
            filetypes=[("Enduro session", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            loaded = SessionModel.from_payload(payload)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            messagebox.showerror("Load failed", f"Could not load this session.\n\n{exc}")
            return
        self.session = loaded
        self.selected_team_id = next(iter(loaded.teams), None)
        self.selected_cart_number = None
        self._undo_stack.clear()
        self.status_var.set(f"Session loaded from {path}")
        self.build_main_ui()

    def confirm_new_session(self) -> None:
        if messagebox.askyesno(
            "New session",
            "Start a new session? Unsaved changes will be lost.",
        ):
            self.session = None
            self.selected_team_id = None
            self.selected_cart_number = None
            self._undo_stack.clear()
            self.status_var.set("Create or load a session")
            self.show_setup_screen()

    def require_session(self) -> SessionModel:
        if self.session is None:
            raise RuntimeError("No active session")
        return self.session


if __name__ == "__main__":
    app = EnduroPitManager()
    app.mainloop()
