# Here you define the commands that will be added to your add-in.
# Each command lives in its own sub-folder with an `entry` module exposing
# start() and stop(). Add a new command by creating a folder, importing its
# entry module here, and appending it to the `commands` list.
from ..lib import fusionAddInUtils as futil

from .carcassMaker import entry as carcassMaker
from .trim import entry as trim
from .editThickness import entry as editThickness
from .shelf import entry as shelf
from .lineBoring import entry as lineBoring
from .convertPanel import entry as convertPanel
from .edgeband import entry as edgeband
from .insertHardware import entry as insertHardware
from .sculpt import entry as sculpt
from .countertop import entry as countertop
from .sheets import entry as sheets
from .cutList import entry as cutList
from .bom import entry as bom
from .settings import entry as settings
from .inspectPanels import entry as inspectPanels  # DEV — remove later

# Fusion automatically calls start() and stop() on each of these.
commands = [
    carcassMaker,
    trim,
    editThickness,
    shelf,
    lineBoring,
    convertPanel,
    edgeband,
    insertHardware,
    sculpt,
    countertop,
    sheets,
    cutList,
    bom,
    settings,
    inspectPanels,  # DEV — remove later
]


# Run the start function in each command. Errors are caught and logged so one
# failing command doesn't prevent the others from loading.
def start():
    for command in commands:
        try:
            command.start()
        except:
            futil.handle_error(f'{command.__name__}.start')


# Run the stop function in each command. Errors are caught and logged so one
# failing teardown doesn't leave the rest of the UI behind.
def stop():
    for command in commands:
        try:
            command.stop()
        except:
            futil.handle_error(f'{command.__name__}.stop')
