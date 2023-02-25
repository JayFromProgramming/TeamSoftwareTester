import msvcrt
import threading
import time

import aiohttp
import asyncio
import logging
import chess

from rich.console import Console
from rich.table import Table
from rich.live import Live

from aiohttp import web

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

class ChessViewer:

    def __init__(self, user_hash, server_url, server_port):

        self.user_hash = user_hash
        self.player_color = None
        self.board = chess.Board()
        self.move_queued = False
        self.queued_move = None
        self.cursor = [0, 0]
        self.piece_selected = False
        self.piece_origin = [0, 0]
        self.selected_piece = None  # type: chess.Piece or None
        self.player = 1
        self.board_state = "Waiting for server..."
        self.server_url = server_url
        self.server_port = server_port

    async def get_board(self):
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
                        if json["changed"]:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(f"http://{self.server_url}:{self.server_port}/room/get_state",
                                                       cookies={"user_hash": self.user_hash}) as resp:
                                    if resp.status == 200:
                                        json = await resp.json()
                                        board_fen = json["board"]
                                        current_color = chess.WHITE if json["current_player"] == "white" else chess.BLACK
                                        self.player_color = chess.WHITE if json["your_color"] == "white" else chess.BLACK

                                        # Update the board state
                                        self.board = None
                                        self.board = chess.Board(board_fen)
                                        self.board.turn = current_color
                                        self.board_state = json["state"]
                                    else:
                                        logging.error(f"Error getting board state: {resp.status}")
                    else:
                        logging.error(f"Error getting board state: {resp.status}")

        except Exception as e:
            logging.error(f"Error getting board state: {e}")

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
        return "White" if color == chess.WHITE else "Black"

    def draw_board(self):
        """
        Draws the board to the console
        :return:
        """
        UI = Table(show_header=False, show_lines=True)
        board_table = Table(show_header=False, show_lines=True)
        # Set the background color of the table to brown

        UI.add_row(f"It's [bold]{self.color_to_str(self.board.turn)}[/bold]'s"
                   f" turn, you are [bold]{self.color_to_str(self.player_color)}[/bold].")
        for i in range(8):
            row = []
            for j in range(8):
                if self.board.piece_at(chess.square(j, i)) is not None:
                    piece = self.board.piece_at(chess.square(j, i))
                    if self.cursor[0] == i and self.cursor[1] == j:
                        row.append(f"[on red]{piece.unicode_symbol()}[/on red]")
                    else:
                        # Bold the piece
                        row.append(f"[bold]{piece.unicode_symbol()}[/bold]")
                else:
                    if self.cursor[0] == i and self.cursor[1] == j:
                        row.append(f"[on red] [/on red]")
                    else:
                        row.append(" ")
            board_table.add_row(*row)

        UI.add_row(board_table)
        UI.add_row(f"Board state: {self.board_state}")
        if self.move_queued:
            UI.add_row(f"Move queued: {self.queued_move} | Press Enter to confirm or space to cancel")
        else:
            over = self.board.piece_at(chess.square(self.cursor[1], self.cursor[0]))
            over = fully_qualified_piece_names[over.symbol()] if over is not None else "Empty"
            UI.add_row(f"Selected piece: {self.selected_piece}"
                       if self.piece_selected else
                       f"Cursor Over: {over}")

        return UI

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
                case b' ':
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
        with Live(self.draw_board(), refresh_per_second=10) as live:
            while True:
                live.update(self.draw_board())
                if loops % 10 == 0:
                    await self.get_board()
                loops += 1
                # Read the keyboard input to move the cursor
                await self.keyboard_thread()
                time.sleep(0.1)

    async def main(self):
        """
        Main loop
        :return:
        """
        await self.update()

