import aiohttp
from pick import pick

import os
import json
import asyncio

from rich.console import Console

from game_rooms.Chess import ChessViewer


class ServerInterface:

    def __init__(self, host="localhost", port=47675, console=None):
        self.console = console
        self.host = host
        self.port = port
        self.server_id = None
        self.user_hash = None
        self.user_name = None
        self.rooms = {}

        self.room_handlers = {
            "Chess": ChessViewer
        }

        if not console:
            self.console = Console()

        if not os.path.exists("logins.json"):
            json.dump({}, open("logins.json", "w"))

        self.logins = json.load(open("logins.json", "r"))

        asyncio.run(self.get_server_id())

        if self.server_id in self.logins:
            asyncio.run(self.get_user(self.logins[self.server_id]))
        else:
            username = self.console.input("Please enter a username: ")
            asyncio.run(self.create_user(username))
            asyncio.run(self.get_user(self.user_hash))

        self.console.print(f"Logged in as {self.user_name}")
        # Save the login
        self.logins[self.server_id] = self.user_hash
        json.dump(self.logins, open("logins.json", "w"), indent=4)

        asyncio.run(self.get_rooms())

    async def get_server_id(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/get_server_id") as response:
                if response.status == 200:
                    json = await response.json()
                    self.server_id = json["server_id"]
                    self.console.print(f"Server ID: {self.server_id}")
                else:
                    self.console.print(f"Failed to get server id: {response.status}")

    async def create_user(self, username="testUser", anonymous=False):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/create_user/{username}") as response:
                reply = await response.json()
                print(reply)
                cookie = reply["user_id"]
                print(cookie)
                self.user_hash = cookie
                return cookie

    async def get_user(self, user_hash):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/login/{user_hash}") as response:
                if response.status == 200:
                    json = await response.json()
                    self.user_hash = user_hash
                    self.user_name = json["username"]
                else:
                    print(f"Failed to get user: {response.status}")
                    # Create a new user
                    username = self.console.input("Please enter a username: ")
                    hash = await self.create_user(username)
                    self.user_hash = hash
                    self.user_hash = username

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

    async def get_save_info(self, room_id):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/room/get_saved_info/{room_id}",
                                   cookies={"user_hash": self.user_hash}) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"Failed to get save info: {response.status}")

    async def load_room(self, room_id):
        # Get the room type
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://{self.host}:{self.port}/room/load_game",
                                    json={"room_id": room_id},
                                    cookies={"user_hash": self.user_hash}) as response:
                if response.status == 200:
                    info = await response.json()
                    room_type = info["room_type"]
                    room_id = info["room_id"]
                    room = self.room_handlers[room_type](self.user_hash, self.host, self.port, self.console)
                    await room.main()
                else:
                    self.console.print(f"Failed to load room {room_id}, status code: {response.status}")

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
        room = self.room_handlers[room_type](self.user_hash, self.host, self.port, self.console)
        await room.main()

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

        # settings = self.room_settings_ui_generator(self.room_handlers[room_type])
        settings = {}

        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://{self.host}:{self.port}/create_room",
                                    json={"room_name": room_name, "room_type": room_type, "password": password,
                                        "room_settings": settings},
                                    cookies={"hash_id": self.user_hash}) as response:
                if response.status == 200:
                    self.console.print(f"Room {room_name} created!")
                    room = self.room_handlers[room_type](self.user_hash, self.host, self.port, self.console)
                    await room.main()
                else:
                    self.console.print(f"Failed to create room {room_name}, status code: {response.status}")

    # def room_settings_ui_generator(self, room_type):
    #     settings = {}
    #     with self.console.screen():
    #
    #         # Create a terminal UI for setting the room settings
    #         for setting in room_type.creation_args:
    #             match setting["type"]:
