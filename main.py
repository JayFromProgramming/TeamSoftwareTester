import os
import sys
import time

from rich.console import Console

from pick import pick

import aiohttp
import asyncio
import json

from rich.progress_bar import ProgressBar

from ServerInterface import ServerInterface
from game_rooms import Chess
from game_rooms.Chess import ChessViewer


class Main:

    def __init__(self):
        self.console = Console()

        if not os.path.exists("servers.json"):
            json.dump({}, open("servers.json", "w"))

        self.servers = json.load(open("servers.json", "r"))

        self.progress_bar = ProgressBar(total=len(self.servers))
        for server, info in self.servers.copy().items():
            online = asyncio.run(self.check_server_status(info["host"], info["port"]))
            if not online:
                self.console.print(f"Server {info['name']} is offline.")
                self.servers[server]["online"] = False
            else:
                self.console.print(f"Server {info['name']} is online.")
                self.servers[server]["online"] = True
            self.progress_bar.update(completed=1)

        for server, info in self.servers.items():
            self.console.print(f"{info['name']} - {info['host']}:{info['port']}")

        title = "Please choose a server: "
        options = [f"{info['name']} @ {info['host']}:{info['port']} - {'Online' if info['online'] else 'Offline'}"
                   for server, info in self.servers.items()]
        options.append("Add New Server")
        options.append("Exit")
        option, index = pick(options, title, indicator="=>")

        if option == "Add New Server":
            host = self.console.input("Please enter the host: ")
            port = self.console.input("Please enter the port: ")
        elif option == "Exit":
            sys.exit(0)
        else:
            # Determine selection from index
            host = self.servers[list(self.servers.keys())[index]]["host"]
            port = self.servers[list(self.servers.keys())[index]]["port"]

        # Look for user.txt in the same directory as this file.
        # If it doesn't exist, connect to the server and create a new user.
        self.server_interface = ServerInterface(host=host, port=port, console=self.console)

    async def check_server_status(self, host, port):
        """
        Checks the status of the server.
        :return:
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{host}:{port}/get_server_id") as response:
                    if response.status == 200:
                        json = await response.json()
                        # self.server_id = json["server_id"]
                        # self.server_name = json["server_name"]
                        return True
                    else:
                        return False
        except Exception as e:
            return False

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


if __name__ == "__main__":
    # Check if this client should be ananonymous via a command line argument
    Main().main()
