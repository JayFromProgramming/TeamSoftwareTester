import os
import struct
import sys
import time

from rich.console import Console

from pick import pick

import aiohttp
import asyncio
import json
import socket

from ServerInterface import ServerInterface


class Main:

    def __init__(self):
        self.console = Console()
        discovered_servers = self.multicast_discovery()

        if not os.path.exists("servers.json"):
            json.dump({}, open("servers.json", "w"))

        self.servers = json.load(open("servers.json", "r"))
        self.servers.update(discovered_servers)
        self.console.print("Checking server status...")

        for server, info in self.servers.copy().items():
            if not info["online"]:
                self.console.print(f"{info['name']}@{info['host']}:{info['port']}".ljust(45) + " - [red]OFFLINE[/red]")
            elif "known" not in info:
                self.console.print(f"{info['name']}@{info['host']}:{info['port']}".ljust(
                    45) + f" - [blue]DISCOVERED {info['response_time']:.2f}ms[/blue]")
            else:
                self.console.print(f"{info['name']}@{info['host']}:{info['port']}".ljust(
                    45) + f" - [green]ONLINE {info['response_time']:.2f}ms[/green]")

        time.sleep(1)

        title = "Please choose a server: "
        options = []
        for server, info in self.servers.items():
            if not info["online"]:
                options.append(f"{info['name']}@{info['host']}:{info['port']}".ljust(45) + " - OFFLINE")
            elif "known" not in info:
                options.append(f"{info['name']}@{info['host']}:{info['port']}".ljust(
                    45) + f" - DISCOVERED {info['response_time']:.2f}ms")
            else:
                options.append(f"{info['name']}@{info['host']}:{info['port']}".ljust(
                    45) + f" - ONLINE {info['response_time']:.2f}ms")

        options.append("Manually add a server")
        options.append("Exit")
        option, index = pick(options, title, indicator="=>")

        if option == "Manually add a server":
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
            start_time = time.time()
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{host}:{port}/get_server_id") as response:
                    if response.status == 200:
                        # Get the response time
                        return (time.time() - start_time) * 1000
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

    def multicast_discovery(self):
        """
        Send a multicast message to find servers on the network
        """
        self.console.print("Preforming multicast discovery...")
        multicast_group = ('225.0.0.250', 47674)

        # Create the socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Set a timeout so the socket does not block indefinitely when trying
        # to receive data.
        sock.settimeout(0.2)

        # Set the time-to-live for messages to 1 so they do not go past the
        # local network segment.
        ttl = struct.pack('b', 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        servers = {}
        try:
            # Send data to the multicast group
            # self.console.print('sending "%s"' % "DISCOVER")
            sent = sock.sendto("DISCOVER".encode(), multicast_group)
            start_time = time.time()
            # Look for responses from all recipients
            while True:
                try:
                    data, server = sock.recvfrom(1024)
                    end_time = time.time()
                    json_data = json.loads(data.decode())
                    for host in json_data["host"]:
                        if server[0] == host:
                            json_data["host"] = host
                    json_data["response_time"] = (end_time - start_time) * 1000
                    json_data["online"] = True
                    servers.update({server[0]: json_data})
                except socket.timeout:
                    break
        except Exception as e:
            self.console.print(f"{type(e)}: {e}")

        return servers


if __name__ == "__main__":
    # Check if this client should be ananonymous via a command line argument
    Main().main()
