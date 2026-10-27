# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""When the app looks for updates by itself (Settings' "Check for Updates"). The button in About always
works; this only decides whether a check also runs at launch."""

STARTUP = "Check on Start Up"
NEVER = "Never"
MODES = [STARTUP, NEVER]
DEFAULT_MODE = STARTUP
