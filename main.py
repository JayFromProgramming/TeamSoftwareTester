import os
import time

from rich.console import Console

from pick import pick

import aiohttp
import asyncio
import json


class Main:

    def __init__(self):
        self.console = Console()
        # Look for user.txt in the same directory as this file.
        # If it doesn't exist, connect to the server and create a new user.

        if not os.path.exists("user.txt"):
            username = self.console.input("Please enter a username: ")
            user_hash = asyncio.run(self.create_user(username))
            user_info = asyncio.run(self.get_user(user_hash))["username"]
        else:
            print("Loading user")
            with open("user.txt", "r") as f:
                user_hash = f.read()
            user_info = asyncio.run(self.get_user(user_hash))["username"]

        self.user_hash = user_hash
        self.user_name = user_info
        self.rooms = {}

    async def create_user(self, username="testUser"):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:47675/create_user/{username}") as response:
                reply = await response.json()
                print(reply)
                cookie = reply["user_id"]
                print(cookie)
                with open("user.txt", "w") as f:
                    f.write(cookie)
                return cookie

    async def get_user(self, user_hash):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:47675/login/{user_hash}") as response:
                return await response.json()

    async def get_rooms(self):
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:47675/get_rooms", cookies={"user_hash": self.user_hash}) as response:
                if response.status == 200:
                    rooms = await response.json()
                    for room in rooms:
                        self.rooms[room["name"]] = room
                else:
                    print(f"Failed to get rooms: {response.status}")

    def main(self):
        self.console.print(f"Welcome {self.user_name}!")
        self.console.print("Loading rooms...")
        time.sleep(1)
        asyncio.run(self.get_rooms())
        room_names = ["Create new room"]
        for room_id, room in self.rooms.items():
            room_names.append(f"{room['name']}({room['type']}) - {len(room['users'])}/{room['max_users']} users | "
                              f"Password: {'Yes' if room['password_protected'] else 'No'} | Joinable: {'Yes' if room['joinable'] else 'No'}")
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
            async with session.post("http://localhost:47675/create_room",
                                    json={"room_name": room_name, "room_type": room_type, "password": password},
                                    cookies={"hash_id": self.user_hash}) as response:
                if response.status == 200:
                    self.console.print(f"Room {room_name} created!")
                else:
                    self.console.print(f"Failed to create room {room_name}, status code: {response.status}")

    async def get_valid_rooms(self):
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:47675/get_games", cookies={"hash_id": self.user_hash}) as response:
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
            async with session.post("http://localhost:47675/join_room",
                                    json={"room_id": self.rooms[room_name]["room_id"], "password": password},
                                    cookies={"hash_id": self.user_hash}) as response:
                if response.status == 200:
                    self.console.print(f"Joined room {room_name}!")
                else:
                    self.console.print(f"Failed to join room {room_name}, status code: {response.status}")


if __name__ == "__main__":
    Main().main()
