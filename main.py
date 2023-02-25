import os
import sys
import time

from rich.console import Console

from pick import pick

import aiohttp
import asyncio
import json

from game_rooms import Chess
from game_rooms.Chess import ChessViewer


class Main:

    def __init__(self, host="localhost", port=47675, anonymous=False):
        self.console = Console()
        self.host = host
        self.port = port
        # Look for user.txt in the same directory as this file.
        # If it doesn't exist, connect to the server and create a new user.

        if not os.path.exists("user.txt") or anonymous:
            print("Creating new user")
            username = self.console.input("Please enter a username: ")
            user_hash = asyncio.run(self.create_user(username, anonymous))
            user_name = asyncio.run(self.get_user(user_hash))["username"]
        else:
            print("Loading user")
            with open("user.txt", "r") as f:
                user_hash = f.read()
            user_name = asyncio.run(self.get_user(user_hash))["username"]

        self.user_hash = user_hash
        self.user_name = user_name
        print(f"Logged in as {user_name}")
        self.rooms = {}

        self.room_handlers = {
            "Chess": ChessViewer
        }

    async def create_user(self, username="testUser", anonymous=False):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/create_user/{username}") as response:
                reply = await response.json()
                print(reply)
                cookie = reply["user_id"]
                print(cookie)
                if not anonymous:
                    with open("user.txt", "w") as f:
                        f.write(cookie)
                return cookie

    async def get_user(self, user_hash):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/login/{user_hash}") as response:
                return await response.json()

    async def get_rooms(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/get_rooms",
                                   cookies={"user_hash": self.user_hash}) as response:
                if response.status == 200:
                    rooms = await response.json()
                    for room in rooms:
                        self.rooms[room["name"]] = room
                else:
                    print(f"Failed to get rooms: {response.status}")

    def build_name_list(self):
        names = []
        # Get the longest name so we can format the list nicely
        if len(self.rooms) != 0:
            longest_name = max([len(room) for room in self.rooms.keys()])
        else:
            longest_name = 0
        for room in self.rooms.values():
            name = room["name"].ljust(longest_name)
            names.append(f"{name}({room['type']}) - {len(room['users'])}/{room['max_users']} users | "
                         f"Password: {'Yes' if room['password_protected'] else 'No'} | Joinable: {'Yes' if room['joinable'] else 'No'}")
        return names

    def main(self):

        # Create a header that will be displayed at the top of the screen and persist

        self.console.print("Loading rooms...")
        time.sleep(1)
        asyncio.run(self.get_rooms())
        room_names = ["Create new room"]
        room_names.extend(self.build_name_list())
        room_names.append("Quit")
        title = "Please choose a room: "
        option, index = pick(room_names, title, indicator="=>")
        if option == "Create new room":
            asyncio.run(self.create_room())
        elif option == "Quit":
            self.console.print("Goodbye!")
        else:
            # Get the room by the index
            room_name = list(self.rooms.keys())[index - 1]
            self.console.print(f"Joining room {room_name}...")
            asyncio.run(self.join_room(room_name))

    async def create_room(self):

        valid_rooms = await self.get_valid_rooms()

        room_name = self.console.input("Please enter a room name: ")
        # Ask if the room should be password protected
        password_protected = pick(["No", "Yes"], "Should the room be password protected?", indicator="=>")[0]
        if password_protected == "Yes":
            password = self.console.input("Please enter a password: ")
        else:
            password = None
        # Ask what type of room it is
        room_type = pick(valid_rooms, "Please choose a room type:", indicator="=>")[0]

        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://{self.host}:{self.port}/create_room",
                                    json={"room_name": room_name, "room_type": room_type, "password": password},
                                    cookies={"hash_id": self.user_hash}) as response:
                if response.status == 200:
                    self.console.print(f"Room {room_name} created!")
                    room = self.room_handlers[room_type](self.user_hash, "localhost", 47675)
                    await room.main()
                else:
                    self.console.print(f"Failed to create room {room_name}, status code: {response.status}")

    async def get_valid_rooms(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/get_games",
                                   cookies={"hash_id": self.user_hash}) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.console.print(f"Failed to get valid rooms, status code: {response.status}")

    async def join_room(self, room_name):
        # print(self.rooms[room_name])
        if self.rooms[room_name]["password_protected"]:
            password = self.console.input("Please enter the password: ")
        else:
            password = None
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://{self.host}:{self.port}/join_room",
                                    json={"room_id": self.rooms[room_name]["room_id"], "password": password},
                                    cookies={"hash_id": self.user_hash}) as response:
                if response.status == 200:
                    self.console.print(f"Joined room {room_name}!")
                else:
                    self.console.print(f"Failed to join room {room_name}, status code: {response.status}")

        # Get the room type and create an instance of it
        room_type = self.rooms[room_name]["type"]
        room = self.room_handlers[room_type](self.user_hash, self.host, self.port)
        await room.main()


if __name__ == "__main__":
    # Check if this client should be ananonymous via a command line argument
    host = "wopr.eggs.loafclan.org"
    port = 47675
    if len(sys.argv) > 1:
        if sys.argv[1] == "--anonymous":
            Main(host, port, anonymous=True).main()
            exit(0)
        else:
            print("Invalid argument")
    Main(host=host, port=port).main()
