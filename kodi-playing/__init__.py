#!/usr/bin/env python3 -OO
# -OO: Turn on basic optimizations.  Given twice, causes docstrings to be discarded.

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

import sys
import subprocess
import getpass
import signal
from .kodi import KodiPlaying
from .dialogs import ErrorDialog

def uncaught_excepthook(*args):
    sys.__excepthook__(*args)
    if __debug__:
        from pprint import pprint
        from types import BuiltinFunctionType, ClassType, ModuleType, TypeType
        tb = sys.last_traceback
        while tb.tb_next: tb = tb.tb_next
        print(('\nDumping locals() ...'))
        pprint({k:v for k,v in tb.tb_frame.f_locals.items()
                    if not k.startswith('_') and
                       not isinstance(v, (BuiltinFunctionType,
                                          ClassType, ModuleType, TypeType))})
        if sys.stdin.isatty() and (sys.stdout.isatty() or sys.stderr.isatty()):
            can_debug = False
            try:
                import ipdb as pdb  # try to import the IPython debugger
                can_debug = True
            except ImportError:
                try:
                    import pdb as pdb
                    can_debug = True
                except ImportError:
                    pass

            if can_debug:
                print(('\nStarting interactive debug prompt ...'))
                pdb.pm()
    else:
        import traceback
        from pathlib import Path
        details = '\n'.join(traceback.format_exception(*args)).replace('<', '').replace('>', '')
        # Save to error file
        error_file = join(Path.home(), ".kodi-playing/error.log")
        with open(error_file) as f:
            f.write(details)
        title = 'Unexpected error'
        msg = "Please submit a bug report: %s" % error_file
        ErrorDialog(title, "<b>%s</b>" % msg, "<tt>%s</tt>" % details, None, True, 'live-installer-3')

    sys.exit(1)

sys.excepthook = uncaught_excepthook

def main():
    # Check if already running
    cmd = "pgrep -u %s -f python3.*kodi-playing" % getpass.getuser()
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pid, err = process.communicate()
    if len(pid.splitlines()) > 1:
        print(("kodi-playing is already running - exiting"))
    else:
        KodiPlaying()
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        Gtk.main()
    
if __name__ == '__main__':
    main()
