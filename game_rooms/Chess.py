import datetime
import msvcrt
import os
import threading
import time
import traceback

import aiohttp
import asyncio
import logging
import chess
import chess.variant

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live

from aiohttp import web
from rich.text import Text

from game_rooms.BaseRoom import BaseRoom


def bool_to_color(value):
    if value is True:
        return chess.WHITE
    elif value is False:
        return chess.BLACK
    else:
        return None


class Chess(BaseRoom):

    playable = True

    fully_qualified_piece_names = {
        "P": "White Pawn",
        "N": "White Knight",
        "B": "White Bishop",
        "R": "White Rook",
        "Q": "White Queen",
        "K": "White King",
        "p": "Black Pawn",
        "n": "Black Knight",
        "b": "Black Bishop",
        "r": "Black Rook",
        "q": "Black Queen",
        "k": "Black King",
        None: "Empty"
    }

    # Arguments that the server needs when creating a new game
    creation_args = {
        "timers_enabled": {"name": "Timers Enabled", "type": "bool", "default": False, "cords": [0, 0]},
        "time_added_per_move": {"name": "Time Added Per Move", "type": "time", "default": 10, "cords": [0, 1]},
        "white_time": {"name": "White Time", "type": "time", "default": 300, "cords": [0, 2]},
        "black_time": {"name": "Black Time", "type": "time", "default": 300, "cords": [0, 3]},
        "chess_variant": {"name": "Chess Variant", "type": "list", "default": "Standard", "cords": [1, 0],
                          "options": ["Standard", "Chess960", "Crazyhouse", "Three Check", "King of the Hill",
                                      "Antichess", "Atomic", "Horde", "Racing Kings"]},
        "allow_spectators": {"name": "Allow Spectators", "type": "bool", "default": True, "cords": [1, 2]},
    }

    def __init__(self, user_hash, server_url, server_port, console: Console, room_name="Unknown"):
        super().__init__(user_hash, server_url, server_port, console, room_name)
        self.player_color = None
        self.board = chess.Board()
        self.move_queued = False
        self.queued_move = None
        self.cursor = [0, 0]
        self.board_relative_cursor = [0, 0]
        self.piece_selected = False
        self.piece_origin = [0, 0]
        self.selected_piece = None  # type: chess.Piece or None
        self.player = 1
        self.board_state = "Waiting for server..."
        self.last_move = None
        self.taken_pieces = {"white": [], "black": []}
        self.players = {}
        self.start_time = datetime.datetime.now()
        self.spectators = {}
        self.variant = "Standard"

        self.timers_enabled = False
        self.move_timers = [0, 0]  # type: list[int] # In seconds

        self.layout = Layout()
        self.layout.split_column(
            Layout(name="top", ratio=5),
            Layout(name="bottom", ratio=1)
        )
        self.layout["top"].split_row(
            Layout(name="game", ratio=8),
            Layout(name="clients", ratio=4),
        )
        self.layout["bottom"].split_row(
            Layout(name="last_move", ratio=1),
            Layout(name="timers", ratio=1),
        )
        self.layout["top"]["clients"].split_column(
            Layout(name="players", ratio=1),
            Layout(name="spectators", ratio=1),
        )
        self.layout["top"]["game"].split_row(
            Layout(name="board", ratio=1, minimum_size=44),
            Layout(name="game_info", ratio=1),
        )
        self.timer_layout = Layout()
        self.timer_layout.split_row(
            Layout(name="white_timer", ratio=1),
            Layout(name="black_timer", ratio=1),
        )

    def switch_board_variant(self, server_variant):
        """
        If the server variant is different from the current board variant, instantiate a new board of the correct variant
        :return:
        """
        if type(self.board).__name__ != server_variant:
            self.variant = server_variant
            match server_variant:
                case "Board":
                    self.board = chess.Board()
                case "Chess960":
                    self.board = chess.Board(chess960=True)
                case "Crazyhouse":
                    self.board = chess.variant.CrazyhouseBoard()
                case "Three Check":
                    self.board = chess.variant.ThreeCheckBoard()
                case "King of the Hill":
                    self.board = chess.variant.KingOfTheHillBoard()
                case "Antichess":
                    self.board = chess.variant.AntichessBoard()
                case "Atomic":
                    self.board = chess.variant.AtomicBoard()
                case "Horde":
                    self.board = chess.variant.HordeBoard()
                case "Racing Kings":
                    self.board = chess.variant.RacingKingsBoard()
                case _:
                    self.board = chess.Board()

    async def send_save_request(self):
        """
        Sends a save request to the server
        :return:
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://{self.server_url}:{self.server_port}/room/save_game",
                                    cookies={"user_hash": self.user_hash}) as resp:
                if resp.status == 200:
                    json = await resp.json()
                    if "room_id" in json:
                        # Check if a save folder exists
                        if not os.path.exists("saves"):
                            os.mkdir("saves")
                        # Check if a save file exists
                        with open(f"saves/{self.start_time.strftime('%Y-%m-%d_%H-%M-%S')}.room", "w") as file:
                            file.write(json["room_id"])
                        self.console.print("Game saved successfully!")
                    else:
                        self.console.print("Failed to save game!")
                else:
                    self.console.print("Failed to save game!")

    async def get_board(self, force=False):
        """
        Gets the board state from the server
        :return:
        """
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
                            self.move_timers = json["frequent_update"]["move_timers"]
                        if json["changed"] or force:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(f"http://{self.server_url}:{self.server_port}/room/get_state",
                                                       cookies={"user_hash": self.user_hash}) as resp:
                                    if resp.status == 200:
                                        json = await resp.json()
                                        self.switch_board_variant(json["variant"])  # Switch the board variant if needed
                                        board_epd = json["board"]
                                        current_color = bool_to_color(json["current_player"])
                                        self.player_color = bool_to_color(json["your_color"])
                                        # Update the board state
                                        self.board.set_epd(board_epd)
                                        self.board.turn = current_color
                                        self.board_state = json["state"]
                                        self.last_move = json["last_move"]
                                        self.timers_enabled = json["timers_enabled"]
                                        self.taken_pieces = json["taken_pieces"]
                                        # Play the console bell sound when the board changes
                                        self.console.bell()
                                    else:
                                        logging.error(f"Error getting board state: {resp.status}: {await resp.text()}")
                    else:
                        logging.error(f"Error getting board state: {resp.status}: {await resp.text()}")

        except Exception as e:
            logging.error(f"Error getting board state: {e} {traceback.format_exc()}")

    async def send_move(self, move: chess.Move):
        """
        Sends a move to the server
        :param move:
        :return:
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"http://{self.server_url}:{self.server_port}/room/make_move",
                                        cookies={"user_hash": self.user_hash},
                                        json={"move": move.uci()}) as resp:
                    if resp.status != 200:
                        logging.error(f"Error sending move: {resp.status}")
                        # Reset the board state
                        self.board.move_stack.pop()
        except Exception as e:
            logging.error(f"Error sending move: {e}")

    def color_to_str(self, color):
        if color == chess.WHITE:
            return "White"
        elif color == chess.BLACK:
            return "Black"
        else:
            return "Not playing"

    def is_promotion(self, move: chess.Move):
        """
        Checks if a move is of a pawn promotion
        :param move:
        :return:
        """
        piece = self.board.piece_at(move.from_square)
        if piece is not None:
            if piece.piece_type == chess.PAWN:
                if self.board.turn == chess.WHITE:
                    if move.to_square in chess.SquareSet(chess.BB_RANK_8) and move.from_square in chess.SquareSet(
                            chess.BB_RANK_7):
                        return True
                else:
                    if move.to_square in chess.SquareSet(chess.BB_RANK_1) and move.from_square in chess.SquareSet(
                            chess.BB_RANK_2):
                        return True

    def piece_has_valid_moves(self, piece, square):
        """
        Checks if a piece has any valid moves
        :param piece: A chess.Piece object
        :return:
        """
        for move in self.board.legal_moves:
            if move.from_square == square:
                return True
        return False

    def valid_cursor_selection(self):
        """
        Checks if the cursor is over a valid piece
        :return:
        """
        if self.board.turn != self.player_color:
            return False
        square = chess.square(self.cursor[1], self.cursor[0])
        piece = self.board.piece_at(square)
        if not self.piece_selected:  # If no piece is selected, check if the cursor is over a valid piece
            if piece is not None:  # Check if the cursor is over a piece
                if piece.color == self.board.turn and self.piece_has_valid_moves(piece, square):
                    # Check if the piece has any valid moves
                    return True
            return False
        else:  # If a piece is already selected, check if the cursor is over a valid move
            move = chess.Move(chess.square(self.piece_origin[1], self.piece_origin[0]),
                              chess.square(self.cursor[1], self.cursor[0]))
            if move in self.board.legal_moves:
                return True

    def draw_timers(self):
        """
        Draws the timers
        :return:
        """
        if self.timers_enabled:
            self.timer_layout["white_timer"].update(Panel(Text(f"{datetime.timedelta(seconds=self.move_timers[0])}",
                                                               justify="center"),
                                                          style="white" if self.move_timers[0] > 30 else "orange_red1"
                                                          if self.move_timers[0] > 0 else "red",
                                                          title="White", subtitle_align="center"))
            self.timer_layout["black_timer"].update(Panel(Text(f"{datetime.timedelta(seconds=self.move_timers[1])}",
                                                               justify="center"),
                                                          style="white" if self.move_timers[1] > 30 else "orange_red1"
                                                          if self.move_timers[1] > 0 else "red",
                                                          title="Black", subtitle_align="center"))
        else:
            self.timer_layout["white_timer"].update(Panel(Text(f"N/A", justify="center"),
                                                          style="white", title="White",
                                                          subtitle_align="center"))
            self.timer_layout["black_timer"].update(Panel(Text(f"N/A", justify="center"),
                                                          style="white", title="Black",
                                                          subtitle_align="center"))

    def game_info_panel(self):
        """
        Draws the game info panel
        :return:
        """
        taken_black_pieces = []
        taken_white_pieces = []
        for piece in self.taken_pieces["black"]:
            chess_piece = chess.Piece.from_symbol(piece)
            taken_black_pieces.append(self.piece_character(chess_piece))
        for piece in self.taken_pieces["white"]:
            chess_piece = chess.Piece.from_symbol(piece)
            taken_white_pieces.append(self.piece_character(chess_piece))

        text = f"Room Name: {self.room_name}\n" \
               f"Variant: {self.variant}\n" \
               f"Game State: {self.board_state}\n" \
               f"Taken White Pieces: {len(taken_white_pieces)}\n{''.join(taken_white_pieces)}\n" \
               f"Taken Black Pieces: {len(taken_black_pieces)}\n{''.join(taken_black_pieces)}\n"
        game_info = Panel(text, style="white", title="Game Info", subtitle_align="center")
        return game_info

    def draw_ui(self):
        # Draw the ui using the Layout object
        board = self.draw_board()
        board_table = Table(show_header=False, show_lines=True, style="white")
        board_table.add_column("Board", justify="left")
        board_table.add_row(f"It's [bold]{self.color_to_str(self.board.turn)}[/bold]'s turn,"
                            f" you are [bold]{self.color_to_str(self.player_color)}[/bold]")
        board_table.add_row(board)
        if self.move_queued:
            board_table.add_row(f"Move queued: {self.queued_move}")
        elif self.piece_selected:
            board_table.add_row(f"Selected piece: {self.selected_piece}")
        else:
            over_piece = self.board.piece_at(chess.square(self.cursor[1], self.cursor[0]))
            if over_piece is not None:
                board_table.add_row(f"Cursor over: "
                                    f"{self.fully_qualified_piece_names[over_piece.symbol()]}")
            else:
                board_table.add_row(f"Cursor over: Empty square")
        player_table, spectator_table = self.draw_player_table()
        self.layout["top"]["game"]["board"].update(Panel(board_table, title="Board"))
        self.layout["top"]["game"]["game_info"].update(self.game_info_panel())
        self.layout["top"]["clients"]["players"].update(Panel(player_table, title="Players"))
        self.layout["top"]["clients"]["spectators"].update(Panel(spectator_table, title="Spectators"))
        self.layout["bottom"]["last_move"].update(Panel(f"Last Move: {self.last_move}", title="Last move"))
        self.draw_timers()
        if self.timers_enabled:
            self.layout["bottom"]["timers"].update(Panel(self.timer_layout, title="Timers"))
        else:
            self.layout["bottom"]["timers"].update(Panel(self.timer_layout, title="Timers (disabled)"))

        return self.layout

    def piece_character(self, piece):
        if piece.color == chess.WHITE:
            return f"[underline white]{piece.unicode_symbol()}[/underline white]"
        else:
            return f"[grey19]{piece.unicode_symbol()}[/grey19]"

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

    def draw_board(self):
        """
        Draws the board to the console
        :return:
        """

        board_table = Table(show_header=False, show_lines=True, border_style="orange4")
        # Set the background color of the table to brown

        for i in range(8):
            row = []
            for j in range(8):
                if self.board.piece_at(chess.square(j, i)) is not None:
                    piece = self.board.piece_at(chess.square(j, i))
                    if self.cursor[0] == i and self.cursor[1] == j:
                        if self.valid_cursor_selection():
                            row.append(f"[black on grey19]{self.piece_character(piece)}[/black on grey19]")
                        else:
                            row.append(f"[black on red]{self.piece_character(piece)}[/black on red]")
                    else:
                        row.append(f"[grey19]{self.piece_character(piece)}[/grey19]")
                else:
                    if self.cursor[0] == i and self.cursor[1] == j:
                        if self.valid_cursor_selection():
                            row.append(f"[green]*[/green]")
                        else:
                            row.append(f"*")

                    else:
                        row.append(" ")
            board_table.add_row(*row)
        return board_table

    async def keyboard_thread(self):
        if msvcrt.kbhit():
            key = msvcrt.getch()
            # print(key)
            match key:
                case b'H':
                    self.cursor[0] -= 1 if self.cursor[0] > 0 else 0
                case b'P':
                    self.cursor[0] += 1 if self.cursor[0] < 7 else 0
                case b'K':
                    self.cursor[1] -= 1 if self.cursor[1] > 0 else 0
                case b'M':
                    self.cursor[1] += 1 if self.cursor[1] < 7 else 0
                case b'r':
                    await self.get_board(force=True)
                case b's':
                    await self.send_save_request()
                case b' ':
                    if self.move_queued:
                        self.move_queued = False
                        self.queued_move = None
                    else:
                        if self.piece_selected:
                            # Check if the move is valid
                            move = chess.Move(chess.square(self.piece_origin[1], self.piece_origin[0]),
                                              chess.square(self.cursor[1], self.cursor[0]))
                            if move in self.board.legal_moves:
                                # Move the piece
                                self.board.push(move)
                                self.move_queued = True
                                self.queued_move = move
                                self.piece_selected = False
                                self.selected_piece = None
                            elif self.is_promotion(move):
                                move.promotion = chess.QUEEN
                                self.board.push(move)
                                self.move_queued = True
                                self.queued_move = move
                                self.piece_selected = False
                                self.selected_piece = None
                            else:
                                print(f"Invalid move: {move}")
                                self.piece_selected = False
                                self.selected_piece = None
                        else:
                            self.piece_selected = True
                            self.selected_piece = self.board.piece_at(chess.square(self.cursor[1], self.cursor[0]))
                            self.piece_origin = self.cursor.copy()
                case b'\r':
                    if self.move_queued:
                        # Remember to flip the move back to the server's perspective if the player is white
                        await self.send_move(self.queued_move)
                        self.move_queued = False
                        self.queued_move = None
                case b'q':
                    exit(0)

    async def update(self):
        """
        Uses Live to update the displayed board
        :return:
        """
        loops = 0
        await self.get_board()

        with Live(self.draw_ui(), refresh_per_second=14) as live:
            while True:
                live.update(self.draw_ui())
                if loops % 14 == 0:
                    await self.get_board()
                    loops = 0
                loops += 1
                # Read the keyboard input to move the cursor
                await self.keyboard_thread()
                # Wait 1/14th of a second
                await asyncio.sleep(1 / 14)

    async def main(self):
        """
        Main loop
        :return:
        """
        await self.update()
