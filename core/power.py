"""Settings' "When Done:" — what the machine (or the app) does once the Queue
has finished its last job. No UI code: `perform()` only ever touches Windows.

`QUIT` isn't handled here — closing LlamaMXD is the window's own job — and
`DO_NOTHING` is simply no action. The four that end or suspend the user's
session (`SYSTEM_ACTIONS`) are the ones the UI gives a cancellable countdown
first."""
import os
import subprocess

DO_NOTHING = "Do Nothing"
SHUTDOWN = "Shutdown"
SLEEP = "Sleep"
HIBERNATE = "Hibernate"
LOCK = "Lock System"
LOG_OFF = "Log Off"
QUIT = "Quit LlamaMXD"

ACTIONS = [DO_NOTHING, SHUTDOWN, SLEEP, HIBERNATE, LOCK, LOG_OFF, QUIT]
SYSTEM_ACTIONS = (SHUTDOWN, SLEEP, HIBERNATE, LOG_OFF)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# shutdown.exe covers three of them; /t 0 = immediately (the UI already gave
# its own countdown), and no /f so an app holding unsaved work can still object.
_SHUTDOWN_ARGS = {SHUTDOWN: ["/s", "/t", "0"], HIBERNATE: ["/h"], LOG_OFF: ["/l"]}


def command_for(action):
    """The argv that performs `action` via shutdown.exe, or None for the
    ones that use an API call (Sleep, Lock) or need no process at all."""
    args = _SHUTDOWN_ARGS.get(action)
    return ["shutdown", *args] if args else None


def perform(action):
    """Carries out `action`. Returns an error string, or None on success."""
    if os.name != "nt":
        return "This is only supported on Windows."
    try:
        argv = command_for(action)
        if argv:
            subprocess.Popen(argv, creationflags=_NO_WINDOW)
        elif action == SLEEP:
            import ctypes
            # (hibernate=False, forceCritical=False, disableWakeEvent=False).
            # The API rather than `rundll32 powrprof.dll,SetSuspendState`,
            # which is known to hibernate instead when hibernation is enabled.
            ctypes.windll.powrprof.SetSuspendState(False, False, False)
        elif action == LOCK:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
    except OSError as exc:
        return f"Couldn't {action.lower()}: {exc.strerror or exc}"
    return None
