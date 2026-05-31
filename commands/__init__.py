# Here you define the commands that will be added to your add-in.
# Each command lives in its own sub-folder with an `entry` module exposing
# start() and stop(). Add a new command by creating a folder, importing its
# entry module here, and appending it to the `commands` list.
from .dressUp import entry as dressUp
from .trim import entry as trim

# Fusion automatically calls start() and stop() on each of these.
commands = [
    dressUp,
    trim,
]


# Run the start function in each command. Errors are caught and logged so one
# failing command doesn't prevent the others from loading.
def start():
    for command in commands:
        command.start()


# Run the stop function in each command. Errors are caught and logged.
def stop():
    for command in commands:
        command.stop()
