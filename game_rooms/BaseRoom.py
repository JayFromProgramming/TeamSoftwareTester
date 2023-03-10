from rich.console import Console


class BaseRoom:
    playable = False

    creation_args = {}

    def __init__(self, user_hash, server_url, server_port, console: Console, room_name="Unknown"):
        self.console = console
        self.room_name = room_name
        self.user_hash = user_hash
        self.server_url = server_url
        self.server_port = server_port
        self.players = []
        self.spectators = []

    async def main(self):
        raise NotImplementedError
