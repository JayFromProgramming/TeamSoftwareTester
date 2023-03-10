import struct

import aiohttp
from pick import pick

import os
import json
import asyncio

from rich.console import Console
try:
    from game_rooms.BaseRoom import BaseRoom
    from RoomOptionHandler import RoomOptionHandler
except ImportError:
    print("Failed to import RoomOptionHandler or BaseRoom, still launching but usage will be limited")
except SyntaxError:
    print("Failed to import RoomOptionHandler or BaseRoom, still launching but usage will be limited")

import os

# Import all files in the gamemanagers folder
for file in os.listdir("game_rooms"):
    if file.endswith(".py"):
        try:
            exec(f"from game_rooms.{file[:-3]} import *")
        except Exception as e:
            print(f"Error importing {file}: {e}")


class ServerInterface:
    """
    The server interface handles all the communication with the server up to the point of joining a room.
    At which point it hands off to the room handler.
    """

    def __init__(self, host, port, console):
        self.console = console
        self.host = host  # The host of the server
        self.port = port  # The port of the server
        self.server_id = None  # The server id
        self.server_name = None  # The name of the server
        self.user_hash = None  # The user hash is used to identify the user
        self.user_name = None  # The user name is used to display the user name
        self.rooms = {}  # A dictionary of all the rooms on the server

        if not console:
            self.console = Console()

        self.room_handlers = {}  # A dictionary of all the room handlers
        for room in BaseRoom.__subclasses__():
            if room.playable:
                self.console.print(f"Adding room handler for {room.__name__}")
                self.room_handlers[room.__name__] = room
            else:
                self.console.print(f"Skipping room handler for {room.__name__}")

        self.servers = json.load(open("servers.json", "r"))  # Load the servers from the servers.json file
        asyncio.run(self.get_server_id())  # Get the server id from the server

        if self.server_id in self.servers:  # If we've already logged in to this server
            asyncio.run(self.get_user(self.servers[self.server_id]["user_hash"]))  # Just log in with the user hash
        else:
            username = self.console.input("Please enter a username: ")  # Ask the user for a username
            asyncio.run(self.create_user(username))     # Create a new user
            asyncio.run(self.get_user(self.user_hash))  # Log in with the new user hash

        self.console.print(f"Logged in as {self.user_name}")
        # Save the login
        self.servers.update({self.server_id: {"host": self.host, "port": self.port, "user_hash": self.user_hash,
                                              'name': self.server_name, "online": None, "known": True}})
        json.dump(self.servers, open("servers.json", "w"), indent=4)

        asyncio.run(self.get_rooms())  # Get the rooms from the server

    async def get_server_id(self):
        """
        Gets the server id from the server
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/get_server_id") as response:
                if response.status == 200:  # If the server responded with a 200 OK
                    json = await response.json()
                    self.server_id = json["server_id"]  # Get the server id from the response
                    self.server_name = json["server_name"]  # Get the server name from the response
                    self.console.print(f"Server ID: {self.server_id}\nServer Name: {self.server_name}")
                else:
                    self.console.print(f"Failed to get server id: {response.status}")

    async def create_user(self, username="testUser"):
        """
        Creates a new user on the server
        :param username: The username of the new user
        :return: The user hash of the new user
        """
        async with aiohttp.ClientSession() as session:  # Send a get request to the server for a new user hash
            async with session.get(f"http://{self.host}:{self.port}/create_user/{username}") as response:
                reply = await response.json()
                print(reply)
                cookie = reply["user_id"]  # Get the user id from the response
                print(cookie)
                self.user_hash = cookie
                return cookie

    async def get_user(self, user_hash):
        """
        Gets the username from the server
        :param user_hash: The user hash to get the username for
        """
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
                    self.user_name = username

    async def logout(self):
        """
        Sends a logout request to the server to let it know that the user is no longer connected
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://{self.host}:{self.port}/logout",
                                    cookies={"user_hash": self.user_hash}) as response:
                if response.status == 200:
                    print("Logged out")
                else:
                    print(f"Failed to logout: {response.status}")

    async def get_rooms(self):
        """
        Gets all the active rooms from the server
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/get_rooms",
                                   cookies={"user_hash": self.user_hash}) as response:
                if response.status == 200:
                    rooms = await response.json()
                    rooms = rooms["rooms"]
                    for room in rooms:
                        self.rooms[room["name"]] = room
                else:
                    print(f"Failed to get rooms: {response.status}")

    async def get_save_info(self, room_id):
        """
        Gets the save info for a room
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/room/get_saved_info/{room_id}",
                                   cookies={"user_hash": self.user_hash}) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"Failed to get save info: {response.status}")

    async def load_room(self, room_id):
        """
        Loads information about a room from the server
        """
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
        """
        Gets all the rooms that the user can join
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.host}:{self.port}/get_games",
                                   cookies={"hash_id": self.user_hash}) as response:
                if response.status == 200:
                    valid_rooms = []
                    server_rooms = await response.json()
                    for room in server_rooms:
                        if room not in self.room_handlers:
                            valid_rooms.append((room, False))
                        else:
                            valid_rooms.append((room, True))
                    # Sort the incompatible rooms to the bottom
                    valid_rooms.sort(key=lambda x: x[1], reverse=True)
                    return valid_rooms
                else:
                    self.console.print(f"Failed to get valid rooms, status code: {response.status}")

    async def join_room(self, room_name):
        """
        Attempts to join a room on the server
        :param room_name: The name of the room to join
        """
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
        room = self.room_handlers[room_type](self.user_hash, self.host, self.port, self.console, room_name)
        await room.main()

    async def create_room(self):
        """
        Creates a new room on the server
        """
        valid_rooms = await self.get_valid_rooms()

        room_name = self.console.input("Please enter a room name: ")
        # Ask if the room should be password protected
        # Ask what type of room it is
        room_options = [f"{room}, Incompatible" if not compatible else room for room, compatible in valid_rooms]
        room_type = pick(room_options, "Please choose a room type:", indicator="=>")[0]

        settings = RoomOptionHandler(self.console, self.room_handlers[room_type].creation_args)
        settings.query()
        settings = settings.get_options()

        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://{self.host}:{self.port}/create_room",
                                    json={"room_name": room_name, "room_type": room_type,
                                          "room_config": settings},
                                    cookies={"hash_id": self.user_hash}) as response:
                if response.status == 200:
                    self.console.print(f"Room {room_name} created!")
                    room = self.room_handlers[room_type](self.user_hash, self.host, self.port, self.console, room_name)
                    await room.main()
                else:
                    self.console.print(f"Failed to create room {room_name}, status code: {response.status}")
