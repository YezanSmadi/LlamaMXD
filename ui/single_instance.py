# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""One LlamaMXD at a time: a per-user lock file held for the life of the process."""
import os
import tempfile

from PySide6.QtCore import QLockFile

LOCK_NAME = "LlamaMXD.lock"
ALREADY_RUNNING = "An instance of LlamaMXD is already running"


class InstanceLock:
    """Claims the right to be the running LlamaMXD. `held` is False only when another live
    instance owns the lock. A lock that can't be taken for any other reason (read-only temp
    folder, ...) counts as held: a guard that can't work must never stop the app from starting."""

    def __init__(self):
        # The temp folder is per-user, so two Windows accounts can each run their own copy.
        self._lock = QLockFile(os.path.join(tempfile.gettempdir(), LOCK_NAME))
        # A lock left by a crashed process is still taken over (its PID is no longer running); 0
        # only turns off Qt's age rule, which would otherwise call a live app's lock stale after 30s.
        self._lock.setStaleLockTime(0)
        self.held = self._lock.tryLock(0) or self._lock.error() != QLockFile.LockError.LockFailedError

    def release(self):
        """Frees the lock (a no-op if this process never took it)."""
        if self._lock.isLocked():
            self._lock.unlock()
