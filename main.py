#!/usr/bin/python3

from argparse import ArgumentParser
from uuid import uuid4

from src.loop import mainloop


__version__ = "0.1.0"


def main():
    parser = ArgumentParser(description="Run jaywire agent")
    parser.add_argument(
        "--session",
        type=str,
        default=str(uuid4()),
        help="Session ID to load (optional)"
    )
    args = parser.parse_args()

    print("jaywire", __version__)

    try:
        mainloop(session_id=args.session)
    except KeyboardInterrupt:
        print("exiting - session ID", args.session)


if __name__ == "__main__":
    main()