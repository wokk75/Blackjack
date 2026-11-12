import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from client.gui import BlackjackApp


def main() -> None:
    app = BlackjackApp()
    app.mainloop()


if __name__ == "__main__":
    main()