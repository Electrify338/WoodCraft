# Here you define the commands that will be added to your add-in.
# Each command lives in its own sub-folder with an `entry` module exposing
# start() and stop(). Add a new command by creating a folder, importing its
# entry module here, and appending it to the `commands` list.
from .carcassMaker import entry as carcassMaker
from .trim import entry as trim
from .editThickness import entry as editThickness
from .shelf import entry as shelf
from .lineBoring import entry as lineBoring
from .convertPanel import entry as convertPanel
from .insertHardware import entry as insertHardware
from .sculpt import entry as sculpt
from .sheets import entry as sheets
from .cutList import entry as cutList
from .bom import entry as bom
from .inspectPanels import entry as inspectPanels  # DEV — remove later

# Fusion automatically calls start() and stop() on each of these.
commands = [
    carcassMaker,
    trim,
    editThickness,
    shelf,
    lineBoring,
    convertPanel,
    insertHardware,
    sculpt,
    sheets,
    cutList,
    bom,
    inspectPanels,  # DEV — remove later
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
