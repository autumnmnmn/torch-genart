
import os
import readline

from argparse import ArgumentParser

from pyt.core import PytSession
from pyt.core.terminal import persona


def main():
    parser = ArgumentParser("snakepyt")
    PytSession.define_cli_args(parser)

    cli_args = parser.parse_args()
    session = PytSession(cli_args)

    try:
        username = os.getlogin()
    except:
        username = ""

    while session.repl_continue:
        try:
            tag = f"{username}: {session.prefix}" if session.prefix else username + ':'
            message = session.log.input(tag)
        except (KeyboardInterrupt, EOFError, SystemExit):
            session.log.blank().log(f"goodbye {session.persona.smile()}").blank()
            session.repl_continue = False
            continue

        session.handle_message(message.lstrip())

if __name__ == "__main__":
    main()

