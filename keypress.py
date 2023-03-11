import os
from select import select

if os.name == 'nt':
    import msvcrt

    def kbhit():
        """
        Returns True if keyboard character was hit (Windows version)
        """
        return msvcrt.kbhit()

    def getch():
        """
        Returns a keyboard character after kbhit() has been called (Windows version)
        """
        return msvcrt.getch()

else:
    import sys, tty, termios

    def kbhit():
        """
        Returns True if keyboard character was hit (Linux version)
        """
        dr,dw,de = select([sys.stdin], [], [], 0)
        return dr != []

    def getch():
        """
        Returns a keyboard character after kbhit() has been called (Linux version)
        """
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch