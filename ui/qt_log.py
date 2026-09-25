# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Routes Qt's own messages (its warnings about bad fonts, geometry, styles, ...) into the log,
so they land beside everything else instead of only on a console the app may not have."""
import logging
import sys

from PySide6.QtCore import QtMsgType, qInstallMessageHandler

from core import llamalog

_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.DEBUG,       # Qt's info chatter is debug detail to us
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def install():
    """Replaces Qt's default message handler. The message still goes to stderr when there is one
    (as Qt's default would), and to the log."""
    lg = llamalog.get("qt")

    def handler(mode, context, message):
        level = _LEVELS.get(mode, logging.WARNING)
        where = f" ({context.file}:{context.line})" if getattr(context, "file", None) else ""
        lg.log(level, "%s%s", message, where)
        if sys.stderr is not None and level >= logging.WARNING:
            try:
                sys.stderr.write(message + "\n")
            except Exception:
                pass

    qInstallMessageHandler(handler)
