import asyncio
import keypress
import traceback

import aiohttp

from game_rooms.BaseRoom import BaseRoom

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table


class BattleShip(BaseRoom):
    playable = True

    ship_types = {
        5: "Carrier",
        4: "Battleship",
        3: "Cruiser",
        2: "Submarine",
        1: "Destroyer"
    }

    creation_args = {
        "board_size": {"name": "Board Size", "type": "int", "default": 10, "cords": [0, 0]},
        "ship_count": {"name": "Ship Count", "type": "int", "default": 5, "cords": [0, 1]},
        "allow_spec": {"name": "Allow Spectators", "type": "bool", "default": True, "cords": [0, 2]},
    }

    class Ship:

        def __init__(self, size, sunk, x=None, y=None, direction=None, placed=False):
            self.size = size
            self.health = [True for _ in range(size)]
            self.x = x
            self.y = y
            self.direction = direction
            self.sunk = sunk
            self.placed = placed

        def on_tile(self, x, y):
            if self.x is None or self.y is None:
                return False
            if self.direction == "horizontal":
                if self.x <= x <= self.x + (self.size - 1) and self.y == y:
                    return True
            else:
                if self.y <= y <= self.y + (self.size - 1) and self.x == x:
                    return True
            return False

        def net_update(self, size, sunk, placed, x=None, y=None, direction=None):
            self.size = size
            self.sunk = sunk
            self.placed = placed
            self.x = x
            self.y = y
            self.direction = direction

        def state_str(self):
            if self.placed:
                if self.sunk:
                    return "[red]Sunk[/red]"
                else:
                    return "[green]Placed[/green]"
            else:
                return "[red]Not Placed[/red]"

        def place_msg(self):
            """
            The json data to send to the server to place the ship
            """
            return {
                "x": self.x,
                "y": self.y,
                "direction": self.direction,
                "size": self.size
            }

        def rotate(self):
            if self.direction == "horizontal":
                self.direction = "vertical"
            else:
                self.direction = "horizontal"

    def __init__(self, user_hash, server_url, server_port, console: Console, room_name="Unknown"):
        super().__init__(user_hash, server_url, server_port, console, room_name)

        self.player_board = []
        self.player_ships = []
        self.opponent_board = []
        self.opponent_ships = []

        self.board_size = 10

        self.state = "Awaiting Boards..."
        self.current_player = None

        self.place_ships = None

        self.cursor = [0, 0]

        self.queued_attack = None
        self.attack_queued = False

        self.placing_ship = None  # The ship that is being placed

        self.layout = Layout()
        self.layout.split_row(
            Layout(name="opponent_board"),
            Layout(name="center_info"),
            Layout(name="player_board"),
        )
        self.layout["center_info"].split_column(
            Layout(name="top_info"),
            Layout(name="players_info"),
            Layout(name="spectators_info"),
        )
        self.layout["opponent_board"].split_column(
            Layout(name="board", ratio=2),
            Layout(name="opponent_info"),
        )
        self.layout["player_board"].split_column(
            Layout(name="board", ratio=2),
            Layout(name="player_info"),
        )

    async def get_board(self, force):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{self.server_url}:{self.server_port}/room/has_changed",
                                       cookies={"user_hash": self.user_hash}) as resp:
                    if resp.status == 200:
                        json = await resp.json()
                        if json is None:
                            raise Exception("Server returned null")
                        if "frequent_update" in json:
                            self.players = json["frequent_update"]["players"]
                            self.spectators = json["frequent_update"]["spectators"]
                            if force:
                                self.player_ships = []
                                self.opponent_ships = []
                        if json["changed"] or force:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(f"http://{self.server_url}:{self.server_port}/room/get_state",
                                                       cookies={"user_hash": self.user_hash}) as resp:
                                    if resp.status == 200:
                                        json = await resp.json()
                                        if json is None:
                                            raise Exception("Server returned null")
                                        self.player_board = json["board"]
                                        self.opponent_board = json["enemy_board"]
                                        self.state = json["state"]
                                        self.current_player = json["current_player"]
                                        self.place_ships = json[
                                            "allow_place_ships"] if "allow_place_ships" in json else False
                                        if not self.player_ships:
                                            self.player_ships = \
                                                [self.Ship(**ship) for ship in self.player_board["ships"]]
                                        else:
                                            for i, ship in enumerate(self.player_ships):
                                                ship.net_update(**self.player_board["ships"][i])
                                        if not self.opponent_ships:
                                            self.opponent_ships = \
                                                [self.Ship(**ship) for ship in self.opponent_board["ships"]]
                                        else:
                                            for i, ship in enumerate(self.opponent_ships):
                                                ship.net_update(**self.opponent_board["ships"][i])
                                        self.board_size = json["board_size"]
                                        self.console.bell()
        except Exception as e:
            self.console.print(f"Board Update Error: {e}\n{traceback.format_exc()}")

    async def send_move(self):
        try:
            async with aiohttp.ClientSession() as session:
                if self.queued_attack:
                    move = {"x": self.queued_attack[0], "y": self.queued_attack[1]}
                if self.placing_ship:
                    move = {
                        "placed_ships": [
                            self.placing_ship.place_msg()
                        ]
                    }
                async with session.post(f"http://{self.server_url}:{self.server_port}/room/make_move",
                                        cookies={"user_hash": self.user_hash},
                                        json={"move": move}) as resp:
                    if resp.status == 200:
                        json = await resp.json()
                        if json is None:
                            raise Exception("Server returned null")
                        if json["success"]:
                            self.queued_attack = None
                            self.attack_queued = False
                            self.placing_ship = None
                        else:
                            self.console.print(f"Move Error: {json['error']}")
        except Exception as e:
            self.console.print(f"Move Error: {e}\n{traceback.format_exc()}")

    def make_board_table(self, board, ships, show_cursor=False):
        table = Table(show_header=False, show_lines=True)
        # Make an empty table with the right size
        for _ in range(len(board)):
            table.add_column()
        # Fill the table with the board
        column_num = 0
        for board_row in board["board"]:
            row = []
            row_num = 0
            for tile in board_row:
                if [ship.on_tile(column_num, row_num) for ship in ships].count(True) > 0:
                    if tile == 1:
                        row.append("[red bold]■[/red bold]")
                    else:
                        row.append("[white bold]■[/white bold]")
                else:
                    if show_cursor and column_num == self.cursor[0] and row_num == self.cursor[1]:
                        if tile == 1:
                            row.append("[red]*[/red]")
                        elif tile == 2:
                            row.append("[blue]*[/blue]")
                        else:
                            row.append("[white]*[/white]")
                    else:
                        if tile == 1:
                            row.append("[red]X[/red]")
                        elif tile == 2:
                            row.append("[white]O[/white]")
                        else:
                            row.append(" ")
                row_num += 1
            column_num += 1
            table.add_row(*row)
        return table

    def ship_info_panel(self, board, player):
        table = Table(show_header=False, show_lines=True)
        table.add_column("Ship")
        table.add_column("Size")
        table.add_column("State")
        ships = [self.Ship(**ship) for ship in board["ships"]]
        for ship in ships:
            table.add_row(self.ship_types[ship.size], str(ship.size), ship.state_str())
        return Panel(table, title=f"{player} Ships")

    def draw_player_table(self):
        player_table = Table(show_header=True, show_lines=True, expand=True)
        spectator_table = Table(show_header=True, show_lines=True, expand=True)
        player_table.add_column("Username", justify="left")
        player_table.add_column("Status", justify="left")
        for player in self.players:
            player_table.add_row(f"{player['username']}",
                                 f"{'[green]Online[/green]' if player['online'] else '[red]Offline[/red]'}")
        spectator_table.add_column("Username", justify="left")
        spectator_table.add_column("Status", justify="left")
        for spectator in self.spectators:
            spectator_table.add_row(f"{spectator['username']}",
                                    f"{'[green]Online[/green]' if spectator['online'] else '[red]Offline[/red]'}")
        return player_table, spectator_table

    def render_center_info(self):
        text = [f"Room: {self.room_name}", f"State: {self.state}",
                f"Current Player: {self.current_player['username'] if self.current_player else 'None'}",
                f"Queued Attack: {self.queued_attack}"]
        return "\n".join(text)

    def draw_ui(self):
        self.layout["player_board"]["board"].update(
            Panel(self.make_board_table(self.player_board, self.player_ships), title="Your Board"))
        self.layout["opponent_board"]["board"].update(
            Panel(self.make_board_table(self.opponent_board, self.opponent_ships, not self.place_ships),
                  title="Opponent Board"))
        self.layout["center_info"]["top_info"].update(Panel(self.render_center_info(), title="Info"))
        self.layout["center_info"]["players_info"].update(Panel(self.draw_player_table()[0], title="Players"))
        self.layout["center_info"]["spectators_info"].update(Panel(self.draw_player_table()[1], title="Spectators"))
        self.layout["opponent_board"]["opponent_info"].update(self.ship_info_panel(self.opponent_board, "Opponent"))
        self.layout["player_board"]["player_info"].update(self.ship_info_panel(self.player_board, "Your"))

        return self.layout

    async def keyboard_thread(self):
        if keypress.kbhit():
            key = keypress.getch()
            # print(key)
            match key:
                case b'H':
                    self.cursor[0] -= 1 if self.cursor[0] > 0 else 0
                case b'P':
                    self.cursor[0] += 1 if self.cursor[0] < self.board_size - 1 else 0
                case b'K':
                    self.cursor[1] -= 1 if self.cursor[1] > 0 else 0
                case b'M':
                    self.cursor[1] += 1 if self.cursor[1] < self.board_size - 1 else 0
                case b'e':
                    if self.place_ships:
                        if self.placing_ship:
                            self.placing_ship.rotate()
                case b'r':
                    await self.get_board(force=True)
                case b' ':
                    if self.place_ships:
                        # Get the first ship that is not placed
                        if self.placing_ship is not None:
                            self.placing_ship.placed = True
                            await self.send_move()
                            self.placing_ship = None
                    else:
                        if not self.attack_queued:
                            self.queued_attack = self.cursor
                            self.attack_queued = True
                        else:
                            self.queued_attack = None
                            self.attack_queued = False
                case b'\r':
                    if self.attack_queued:
                        await self.send_move()
                case b'q':
                    self.running = False
                    self.console.print("Quitting...")

            if self.placing_ship:
                self.placing_ship.x = self.cursor[0]
                self.placing_ship.y = self.cursor[1]

    async def update(self):
        loops = 0

        with Live(self.draw_ui(), refresh_per_second=14) as live:
            while True:
                if loops % 14 == 0:
                    await self.get_board(False)
                    loops = 0
                await self.keyboard_thread()
                live.update(self.draw_ui())
                loops += 1

                if self.place_ships:
                    for ship in self.player_ships:
                        if not ship.placed:
                            self.placing_ship = ship
                            break

                await asyncio.sleep(1 / 14)

    async def main(self):
        await self.get_board(True)
        await self.update()
