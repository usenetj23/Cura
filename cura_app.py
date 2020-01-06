#!/usr/bin/env python3

# Copyright (c) 2019 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

import argparse
import faulthandler
import os
import sys

from UM.Platform import Platform
from cura import ApplicationMetadata
from cura.ApplicationMetadata import CuraAppName

if Platform.isWindows() and hasattr(sys, "frozen"):
    DIR_NAME = os.path.dirname(sys.executable)
    # add DIR_NAME and DIR_NAME/lib to the path so DLLs can be found
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if DIR_NAME not in paths:
        paths.insert(0, os.path.join(DIR_NAME, "lib"))
        paths.insert(0, DIR_NAME)
        os.environ["PATH"] = os.pathsep.join(paths)

try:
    import sentry_sdk
    with_sentry_sdk = True
except ImportError:
    with_sentry_sdk = False

parser = argparse.ArgumentParser(prog = "cura",
                                 add_help = False)
parser.add_argument("--debug",
                    action="store_true",
                    default = False,
                    help = "Turn on the debug mode by setting this option."
                    )

known_args = vars(parser.parse_known_args()[0])

if with_sentry_sdk:
    sentry_env = "production"
    if ApplicationMetadata.CuraVersion == "master":
        sentry_env = "development"
    try:
        if ApplicationMetadata.CuraVersion.split(".")[2] == "99":
            sentry_env = "nightly"
    except IndexError:
        pass
    
    sentry_sdk.init("https://5034bf0054fb4b889f82896326e79b13@sentry.io/1821564",
                    environment = sentry_env,
                    release = "cura%s" % ApplicationMetadata.CuraVersion,
                    default_integrations = False,
                    max_breadcrumbs = 300,
                    server_name = "cura")

if not known_args["debug"]:
    def get_cura_dir_path():
        if Platform.isWindows():
            appdata_path = os.getenv("APPDATA")
            if not appdata_path: #Defensive against the environment variable missing (should never happen).
                appdata_path = "."
            return os.path.join(appdata_path, CuraAppName)
        elif Platform.isLinux():
            return os.path.expanduser("~/.local/share/" + CuraAppName)
        elif Platform.isOSX():
            return os.path.expanduser("~/Library/Logs/" + CuraAppName)

    # Do not redirect stdout and stderr to files if we are running CLI.
    if hasattr(sys, "frozen") and "cli" not in os.path.basename(sys.argv[0]).lower():
        dirpath = get_cura_dir_path()
        os.makedirs(dirpath, exist_ok = True)
        sys.stdout = open(os.path.join(dirpath, "stdout.log"), "w", encoding = "utf-8")
        sys.stderr = open(os.path.join(dirpath, "stderr.log"), "w", encoding = "utf-8")


# WORKAROUND: GITHUB-88 GITHUB-385 GITHUB-612
if Platform.isLinux(): # Needed for platform.linux_distribution, which is not available on Windows and OSX
    # For Ubuntu: https://bugs.launchpad.net/ubuntu/+source/python-qt4/+bug/941826
    # The workaround is only needed on Ubuntu+NVidia drivers. Other drivers are not affected, but fine with this fix.
    try:
        import ctypes
        from ctypes.util import find_library
        libGL = find_library("GL")
        ctypes.CDLL(libGL, ctypes.RTLD_GLOBAL)
    except:
        # GLES-only systems (e.g. ARM Mali) do not have libGL, ignore error
        pass

# When frozen, i.e. installer version, don't let PYTHONPATH mess up the search path for DLLs.
if Platform.isWindows() and hasattr(sys, "frozen"):
    try:
        del os.environ["PYTHONPATH"]
    except KeyError:
        pass

# GITHUB issue #6194: https://github.com/Ultimaker/Cura/issues/6194
# With AppImage 2 on Linux, the current working directory will be somewhere in /tmp/<rand>/usr, which is owned
# by root. For some reason, QDesktopServices.openUrl() requires to have a usable current working directory,
# otherwise it doesn't work. This is a workaround on Linux that before we call QDesktopServices.openUrl(), we
# switch to a directory where the user has the ownership.
if Platform.isLinux() and hasattr(sys, "frozen"):
    os.chdir(os.path.expanduser("~"))

# WORKAROUND: GITHUB-704 GITHUB-708
# It looks like setuptools creates a .pth file in
# the default /usr/lib which causes the default site-packages
# to be inserted into sys.path before PYTHONPATH.
# This can cause issues such as having libsip loaded from
# the system instead of the one provided with Cura, which causes
# incompatibility issues with libArcus
if "PYTHONPATH" in os.environ.keys():                       # If PYTHONPATH is used
    PYTHONPATH = os.environ["PYTHONPATH"].split(os.pathsep) # Get the value, split it..
    PYTHONPATH.reverse()                                    # and reverse it, because we always insert at 1
    for PATH in PYTHONPATH:                                 # Now beginning with the last PATH
        PATH_real = os.path.realpath(PATH)                  # Making the the path "real"
        if PATH_real in sys.path:                           # This should always work, but keep it to be sure..
            sys.path.remove(PATH_real)
        sys.path.insert(1, PATH_real)                       # Insert it at 1 after os.curdir, which is 0.


def exceptHook(hook_type, value, traceback):
    from cura.CrashHandler import CrashHandler
    from cura.CuraApplication import CuraApplication
    has_started = False
    if CuraApplication.Created:
        has_started = CuraApplication.getInstance().started

    #
    # When the exception hook is triggered, the QApplication may not have been initialized yet. In this case, we don't
    # have an QApplication to handle the event loop, which is required by the Crash Dialog.
    # The flag "CuraApplication.Created" is set to True when CuraApplication finishes its constructor call.
    #
    # Before the "started" flag is set to True, the Qt event loop has not started yet. The event loop is a blocking
    # call to the QApplication.exec_(). In this case, we need to:
    #   1. Remove all scheduled events so no more unnecessary events will be processed, such as loading the main dialog,
    #      loading the machine, etc.
    #   2. Start the Qt event loop with exec_() and show the Crash Dialog.
    #
    # If the application has finished its initialization and was running fine, and then something causes a crash,
    # we run the old routine to show the Crash Dialog.
    #
    from PyQt5.Qt import QApplication
    if CuraApplication.Created:
        _crash_handler = CrashHandler(hook_type, value, traceback, has_started)
        if CuraApplication.splash is not None:
            CuraApplication.splash.close()
        if not has_started:
            CuraApplication.getInstance().removePostedEvents(None)
            _crash_handler.early_crash_dialog.show()
            sys.exit(CuraApplication.getInstance().exec_())
        else:
            _crash_handler.show()
    else:
        application = QApplication(sys.argv)
        application.removePostedEvents(None)
        _crash_handler = CrashHandler(hook_type, value, traceback, has_started)
        # This means the QtApplication could be created and so the splash screen. Then Cura closes it
        if CuraApplication.splash is not None:
            CuraApplication.splash.close()
        _crash_handler.early_crash_dialog.show()
        sys.exit(application.exec_())


# Set exception hook to use the crash dialog handler
sys.excepthook = exceptHook
# Enable dumping traceback for all threads
if sys.stderr and not sys.stderr.closed:
    faulthandler.enable(file = sys.stderr, all_threads = True)
elif sys.stdout and not sys.stdout.closed:
    faulthandler.enable(file = sys.stdout, all_threads = True)

# Workaround for a race condition on certain systems where there
# is a race condition between Arcus and PyQt. Importing Arcus
# first seems to prevent Sip from going into a state where it
# tries to create PyQt objects on a non-main thread.
import Arcus #@UnusedImport
import Savitar #@UnusedImport
from cura.CuraApplication import CuraApplication


# WORKAROUND: CURA-6739
# The CTM file loading module in Trimesh requires the OpenCTM library to be dynamically loaded. It uses
# ctypes.util.find_library() to find libopenctm.dylib, but this doesn't seem to look in the ".app" application folder
# on Mac OS X. Adding the search path to environment variables such as DYLD_LIBRARY_PATH and DYLD_FALLBACK_LIBRARY_PATH
# makes it work. The workaround here uses DYLD_FALLBACK_LIBRARY_PATH.
if Platform.isOSX() and getattr(sys, "frozen", False):
    old_env = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    # This is where libopenctm.so is in the .app folder.
    search_path = os.path.join(CuraApplication.getInstallPrefix(), "MacOS")
    path_list = old_env.split(":")
    if search_path not in path_list:
        path_list.append(search_path)
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(path_list)
    import trimesh.exchange.load
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = old_env

# WORKAROUND: CURA-6739
# Similar CTM file loading fix for Linux, but NOTE THAT this doesn't work directly with Python 3.5.7. There's a fix
# for ctypes.util.find_library() in Python 3.6 and 3.7. That fix makes sure that find_library() will check
# LD_LIBRARY_PATH. With Python 3.5, that fix needs to be backported to make this workaround work.
if Platform.isLinux() and getattr(sys, "frozen", False):
    old_env = os.environ.get("LD_LIBRARY_PATH", "")
    # This is where libopenctm.so is in the AppImage.
    search_path = os.path.join(CuraApplication.getInstallPrefix(), "bin")
    path_list = old_env.split(":")
    if search_path not in path_list:
        path_list.append(search_path)
    os.environ["LD_LIBRARY_PATH"] = ":".join(path_list)
    import trimesh.exchange.load
    os.environ["LD_LIBRARY_PATH"] = old_env

app = CuraApplication()
app.run()
