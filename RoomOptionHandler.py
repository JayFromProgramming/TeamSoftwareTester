import datetime
import keypress
import time

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel


class Option:

    def __init__(self, name, option_type, default, cords, options=None):
        self.name = name
        self.option_type = option_type
        self.default = default
        self.value = default
        self.coordinates = cords
        self.options = options
        self.selected = False

        self.list_index = 0

        self.text = Panel(f"{self.value}",
                          title=f"[bold]{self.name}[/bold]",
                          border_style="blue",
                          padding=1,
                          expand=True)

    def _get_value_str(self):
        match self.option_type:
            case "int":
                return f"Value: {self.value}"
            case "bool":
                return f"Enabled: {'Yes' if self.value else 'No'}"
            case "str":
                return f"Value: {self.value}"
            case "list":
                return f"Value: {self.value}"
            case "time":
                return f"Time: {datetime.timedelta(seconds=self.value)}"

    def get_panel(self, highlighted, selected):
        if selected and highlighted:
            border_style = "green"
        elif highlighted:
            border_style = "yellow"
        elif selected:
            border_style = "grey46"
        else:
            border_style = "blue"

        return Panel(f"{self._get_value_str()}",
                     title=f"[bold]{self.name}[/bold]",
                     border_style=border_style,
                     padding=1,
                     expand=True)

    def _arrow_input(self, increment=1):
        if keypress.kbhit():
            key = keypress.getch()
            if key == b"\xe0":
                key = msvcrt.getch()
                if key == b"H":
                    self.value += increment
                elif key == b"P":
                    self.value -= increment
            else:
                if key == b"\r":
                    self.selected = False

    def selected_update(self):
        """
        Called every cycle when the option is selected otherwise it is not called
        :return:
        """
        match self.option_type:
            case "int":
                self._arrow_input()
            case "bool":
                if keypress.kbhit():
                    key = keypress.getch()
                    if key == b"\xe0":
                        key = keypress.getch()
                        if key == b"H":
                            self.value = not self.value
                        elif key == b"P":
                            self.value = not self.value
                    else:
                        if key == b"\r":
                            self.selected = False
            case "list":
                if keypress.kbhit():
                    key = keypress.getch()
                    if key == b"\xe0":
                        key = keypress.getch()
                        if key == b"H":
                            self.list_index += 1
                            if self.list_index >= len(self.options):
                                self.list_index = 0
                            self.value = self.options[self.list_index]
                        elif key == b"P":
                            self.list_index -= 1
                            if self.list_index < 0:
                                self.list_index = len(self.options) - 1
                            self.value = self.options[self.list_index]
                    else:
                        if key == b"\r":
                            self.selected = False

            case "time":
                self._arrow_input(increment=10)


class RoomOptionHandler:

    def __init__(self, console, room_options):
        self.console = console
        self.cursor = [0, 0]
        self.selected = False
        self.room_options = {}
        self.max_cords = (0, 0)
        self.finished = False

        for setting_id, setting_info in room_options.items():
            self.room_options[setting_id] = Option(setting_info["name"], setting_info["type"], setting_info["default"],
                                                   setting_info["cords"], options=setting_info.get("options"))

        self.layout = Layout()

        num_rows = 0
        for setting_id, setting in self.room_options.items():
            if setting.coordinates[1] > num_rows:
                num_rows = setting.coordinates[1]

        # Split each column into the required rows
        rows = []
        for row in range(num_rows + 1):
            rows.append(Layout(name=f"row_{row}", size=30))
        self.layout.split_row(*rows)
        self.max_cords = (0, num_rows)

        for row in range(num_rows + 1):
            num_columns = 0
            for setting_id, setting in self.room_options.items():
                if setting.coordinates[0] > num_columns and setting.coordinates[1] == row:
                    num_columns = setting.coordinates[0]
            columns = []
            for column in range(num_columns + 1):
                columns.append(Layout(name=f"column_{column}", size=5))
            self.layout["row_" + str(row)].split_column(*columns)
            if num_columns > self.max_cords[0]:
                self.max_cords = (num_columns, self.max_cords[1])

    def _update_layout(self):
        for setting_id, setting in self.room_options.items():
            # setting.update()
            self.layout[f"row_{setting.coordinates[1]}"][f"column_{setting.coordinates[0]}"].update(setting.get_panel(
                self.cursor == setting.coordinates, self.selected))
        layout = Layout(name="root")
        layout.update(Panel(self.layout, title="Room Options", border_style="blue", padding=1, expand=True))
        return layout

    def _get_option(self, cords):
        for setting_id, setting in self.room_options.items():
            if setting.coordinates == cords:
                return setting
        return None

    def _move_cursor(self, direction):
        """
        Move the cursor in the specified direction to the next option that is in that direction
        If there is no option in that direction, the cursor will not move
        :param direction: The direction to move the cursor (up, down, left, right)
        :return:
        """
        match direction:
            case "up":
                if self.cursor[0] > 0:
                    self.cursor[0] -= 1
                    while self._get_option(self.cursor) is None:
                        if self.cursor[0] > 0:
                            self.cursor[0] -= 1
                        else:
                            break
            case "down":
                if self.cursor[0] < self.max_cords[0]:
                    self.cursor[0] += 1
                    while self._get_option(self.cursor) is None:
                        if self.cursor[0] < self.max_cords[0]:
                            self.cursor[0] += 1
                        else:
                            break
            case "left":
                if self.cursor[1] > 0:
                    self.cursor[1] -= 1
                    while self._get_option(self.cursor) is None:
                        if self.cursor[1] > 0:
                            self.cursor[1] -= 1
                        else:
                            break
            case "right":
                if self.cursor[1] < self.max_cords[1]:
                    self.cursor[1] += 1
                    while self._get_option(self.cursor) is None:
                        if self.cursor[1] < self.max_cords[1]:
                            self.cursor[1] += 1
                        else:
                            break

    def _select_option(self):
        option = self._get_option(self.cursor)
        if option is not None:
            option.selected = True
            self.selected = True

    def _get_user_input(self):
        if keypress.kbhit():
            key = keypress.getch()
            if key == b"\xe0":  # Special key (arrows, f keys, ins, del, etc.)
                key = keypress.getch()
                match key:
                    case b"H":  # Up arrow
                        self._move_cursor("up")
                    case b"P":  # Down arrow
                        self._move_cursor("down")
                    case b"M":  # Right arrow
                        self._move_cursor("right")
                    case b"K":  # Left arrow
                        self._move_cursor("left")
            elif key == b"\r":  # Enter key
                self.finished = True
            elif key == b" ":
                self._select_option()

    def query(self):
        with Live(self._update_layout(), refresh_per_second=14) as live:
            while not self.finished:
                live.update(self._update_layout())
                if not self.selected:
                    self._get_user_input()
                else:
                    self._get_option(self.cursor).selected_update()
                    if not self._get_option(self.cursor).selected:
                        self.selected = False
                time.sleep(14 / 60)

    def get_options(self):
        options = {}
        for setting_id, setting in self.room_options.items():
            options[setting_id] = setting.value
        return options