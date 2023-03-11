import concurrent
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import os
import struct
import sys
import threading
import time

from rich.console import Console

from pick import pick

import aiohttp
import asyncio
import json
import socket
import netifaces

from ServerInterface import ServerInterface


def get_interfaces():
    """
    Gets all the ip addresses that can be bound to
    """
    interfaces = []
    for interface in netifaces.interfaces():
        try:
            if netifaces.AF_INET in netifaces.ifaddresses(interface):
                for link in netifaces.ifaddresses(interface)[netifaces.AF_INET]:
                    if link["addr"] != "":
                        interfaces.append(link["addr"])
        except Exception as e:
            # logging.debug(f"Error getting interface {interface}: {e}")
            pass
    return interfaces


class Main:

    def __init__(self):
        self.console = Console()
        self.ping_queue = asyncio.Queue()

        if not os.path.exists("servers.json"):
            json.dump({}, open("servers.json", "w"))

        with self.console.status("[bold green]Preforming multicast discovery...[/bold green]") as status:
            discovered_servers = self.multicast_discovery(console_status=status)
            loaded_servers = json.load(open("servers.json", "r"))

            # Merge the two dictionaries, if there are any duplicates, the loaded servers will be used unless
            # the host value is different from the discovered server
            for server in discovered_servers:
                if server in loaded_servers:
                    if loaded_servers[server]["host"] != discovered_servers[server]["host"]:
                        loaded_servers[server] = discovered_servers[server]
                        loaded_servers[server]["known"] = True
                else:
                    loaded_servers[server] = discovered_servers[server]

            self.servers = loaded_servers

            if len(self.servers) != 0:
                longest_name = max([len(info['name']) for info in self.servers.values()])
            else:
                longest_name = 0

            # Check the status of each server
            status.update("[bold green]Queueing server status checks...[/bold green]")
            threading.Thread(target=self.check_server_status, args=(self.servers, self.ping_queue)).start()
            finished = False
            still_pinging = [server_id for server_id in self.servers]
            while not finished:
                # Have the status update display all the server names with pings still in progress
                pinging_servers = [self.servers[server_id]["name"] for server_id in still_pinging]
                status.update(f"[bold green]Checking server status... [{', '.join(pinging_servers)}][/bold green]")
                if self.ping_queue.qsize() > 0:
                    server_id, info = self.ping_queue.get_nowait()
                    still_pinging.remove(server_id)

                    if not info["online"]:
                        self.console.print(
                            "[red  ][OFFLINE][/red  ]".ljust(45) +
                            f"- {info['name'].ljust(longest_name)}@{info['host']}:{info['port']}")
                    elif "error" in info:
                        self.console.print(
                            "[red  ][ERROR][/red  ]".ljust(45) +
                            f"- {info['name'].ljust(longest_name)}@{info['host']}:{info['port']}")
                    elif "known" not in info:
                        self.console.print(
                            f"[blue ][DISCOVERED] {info['response_time']:.2f}ms[/blue ]".ljust(45) +
                            f"- {info['name'].ljust(longest_name)}@{info['host']}:{info['port']}")
                    else:
                        self.console.print(
                            f"[green][ONLINE] {info['response_time']:.2f}ms[/green]".ljust(45) +
                            f"- {info['name'].ljust(longest_name)}@{info['host']}:{info['port']}")
                if len(still_pinging) == 0:
                    finished = True

        time.sleep(1)

        title = "Please choose a server: "
        options = []
        for server, info in self.servers.items():
            if not info["online"]:
                options.append(f"{info['name'].ljust(longest_name)}@{info['host']}:{info['port']}".
                               ljust(45) + " - OFFLINE")
            elif "known" not in info:
                options.append(f"{info['name'].ljust(longest_name)}@{info['host']}:{info['port']}".ljust(
                    45) + f" - DISCOVERED {info['response_time']:.2f}ms")
            else:
                options.append(f"{info['name'].ljust(longest_name)}@{info['host']}:{info['port']}".ljust(
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

    def check_server_status(self, servers, queue):
        """
        Checks the status of the server.
        :return:
        """
        # Start an asyncio executor to run the ping function
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            for server_id, info in servers.items():
                executor.submit(asyncio.run, self.check_server_status_thread(server_id, info, queue))

    @staticmethod
    async def check_server_status_thread(server_id, info, queue):
        try:
            host, port = info["host"], info["port"]
            async with aiohttp.ClientSession() as session:
                start_time = time.time()
                async with session.get(f"http://{host}:{port}/get_server_id", timeout=5) as response:
                    info["response_time"] = (time.time() - start_time) * 1000
                    if response.status == 200:
                        # Update the values of the server
                        info["online"] = True
                        queue.put_nowait((server_id, info))
                    else:
                        info["online"] = False
                        queue.put_nowait((server_id, info))
        except Exception as e:
            info["error"] = e
            queue.put_nowait((server_id, info))

    def build_name_list(self):
        names = []
        # Get the longest name so we can format the list nicely
        if len(self.server_interface.rooms) > 0:
            longest_name = max([len(room) for room in self.server_interface.rooms])
        else:
            longest_name = 0
        option_num = 1
        for room in self.server_interface.rooms.values():
            # self.console.print(room)
            name = room["name"].ljust(longest_name)
            names.append(f"{option_num}# '{name}'({room['type']}) - {len(room['users'])}/{room['max_users']} users | "
                         f"Password: {'Yes' if room['password_protected'] else 'No'} |"
                         f" Joinable: {'Yes' if room['joinable'] else 'No'}")
            option_num += 1
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

    def multicast_discovery(self, timeout=1, port=5007, console_status=None):
        """
        Send a multicast message to find servers on the network
        """

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # create UDP socket
        sock.bind(('', 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        # Set the time-to-live for messages to 1 so they do not go past the local network
        ttl = struct.pack('b', 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

        servers = {}
        start_time = time.time()
        # Calculate the broadcast address for each interface
        num_interfaces = len(netifaces.interfaces())
        count = 0
        for interface in netifaces.interfaces():
            try:
                broadcast = netifaces.ifaddresses(interface)[netifaces.AF_INET][0]['broadcast']
                console_status.update(
                    f"[bold green]Sending discovery message to {broadcast} {count}/{num_interfaces}[/bold green]")
                sock.sendto(b"DISCOVER_GAME_SERVER", (broadcast, port))
            except Exception:
                console_status.update(f"[bold red]Error sending discovery message to {interface}[/bold red]")
            count += 1
        try:
            while True:
                try:
                    data, server = sock.recvfrom(1024)
                    end_time = time.time()
                    json_data = json.loads(data.decode())
                    for host in json_data["host"]:
                        if server[0] == host:
                            json_data["host"] = host
                    if isinstance(json_data["host"], list):
                        continue
                    json_data["response_time"] = (end_time - start_time) * 1000
                    json_data["online"] = True
                    servers.update({json_data["server_id"]: json_data})
                except socket.timeout:
                    break
                except Exception as e:
                    pass
        except Exception as e:
            self.console.print(f"{type(e)}: {e}")

        return servers

    def logout(self):
        self.console.print("Logging out...")
        asyncio.run(self.server_interface.logout())


if __name__ == "__main__":
    # Check if this client should be ananonymous via a command line argument
    main = Main()
    try:
        main.main()
    except KeyboardInterrupt:
        main.logout()
        sys.exit()