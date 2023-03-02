import os
import sys
import time

from rich.console import Console

from pick import pick

import aiohttp
import asyncio
import json

from ServerInterface import ServerInterface
from game_rooms import Chess
from game_rooms.Chess import ChessViewer


class Main:

    def __init__(self, host="localhost", port=47675, anonymous=False):
        self.console = Console()
        self.host = host
        self.port = port
        # Look for user.txt in the same directory as this file.
        # If it doesn't exist, connect to the server and create a new user.
        self.server_interface = ServerInterface(host=self.host, port=self.port, console=self.console)

    def build_name_list(self):
        names = []
        # Get the longest name so we can format the list nicely
        if len(self.server_interface.rooms) > 0:
            longest_name = max([len(room) for room in self.server_interface.rooms])
        else:
            longest_name = 0
        for room in self.server_interface.rooms.values():
            # self.console.print(room)
            name = room["name"].ljust(longest_name)
            names.append(f"{name}({room['type']}) - {len(room['users'])}/{room['max_users']} users | "
                         f"Password: {'Yes' if room['password_protected'] else 'No'} | Joinable: {'Yes' if room['joinable'] else 'No'}")
        return names

    def load_save_files(self):
        """
        Loads save files from the save directory.
        :return:
        """
        save_files = []
        for file in os.listdir("saves"):
            if file.endswith(".room"):
                save_files.append(os.path.join("saves", file))
        return save_files

    def main(self):
        # Create a header that will be displayed at the top of the screen and persist
        self.console.clear()
        time.sleep(1)
        options = ["Load Existing Rooms", "Load Saved Game", "Exit"]
        option, index = pick(options, "Please pick an option", indicator="=>")

        if option == "Load Saved Game":
            self.load_saved_game()
        elif option == "Load Existing Rooms":
            self.load_existing_rooms()
        elif option == "Exit":
            self.console.print("Goodbye!")
            sys.exit()

    def load_saved_game(self):
        # For each save file query the server for the save info
        save_files = self.load_save_files()
        info_json = {}
        for file in save_files:
            with open(file, "r") as f:
                room_id = f.read()
            info_json[room_id] = asyncio.run(self.server_interface.get_save_info(room_id))
        # Display the save files
        save_names = []
        save_names.extend([f"{info['name']}({info['room_type']}) - {len(info['users'])}/{info['max_users']} users | "
                           f"Password: {'Yes' if info['password_protected'] else 'No'} | Joinable: {'Yes' if info['joinable'] else 'No'}"
                           for info in info_json.values() if info is not None])
        save_names.append("Back")
        option, index = pick(save_names, "Please choose a room: ", indicator="=>")
        if option == "Back":
            self.main()
        else:
            # Get the room by the index
            room_id = list(info_json.keys())[index - 1]
            self.console.print(f"Joining room {room_id}...")
            asyncio.run(self.server_interface.join_room(room_id))

    def load_existing_rooms(self):
        self.console.print("Loading rooms...")
        room_names = ["Create new room"]
        room_names.extend(self.build_name_list())
        room_names.append("Refresh")
        room_names.append("Quit")
        option, index = pick(room_names, "Please choose a room: ", indicator="=>")
        if option == "Create new room":
            asyncio.run(self.server_interface.create_room())
        elif option == "Quit":
            self.console.print("Goodbye!")
            sys.exit()
        elif option == "Refresh":
            self.console.print("Refreshing rooms...")
            time.sleep(1)
            asyncio.run(self.server_interface.get_rooms())
            self.main()
        else:
            # Get the room by the index
            room_name = list(self.server_interface.rooms)[index - 1]
            self.console.print(f"Joining room {room_name}...")
            asyncio.run(self.server_interface.join_room(room_name))


async def check_server_status(host, port):
    """
    Checks if the server is running.
    :param host:
    :param port:
    :return:
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://{host}:{port}/get_server_id") as resp:
            if resp.status == 200:
                return True
            else:
                return False


if __name__ == "__main__":
    # Check if this client should be ananonymous via a command line argument
    # host = "wopr.eggs.loafclan.org"
    host = "141.219.208.99"
    # host = "localhost"
    port = 47675
    if len(sys.argv) > 1:
        if sys.argv[1] == "--anonymous":
            Main(host, port, anonymous=True).main()
            exit(0)
        else:
            print("Invalid argument")
    Main(host=host, port=port).main()
