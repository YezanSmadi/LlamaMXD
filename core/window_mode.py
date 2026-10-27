# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""How the main window behaves (Settings' "Window Mode"): a normal resizable
window, a frameless one, or the fixed-size window the app was designed at.
Plain names only — turning one into flags and constraints is `MainWindow`'s
job, since none of it is UI-free."""

WINDOWED = "Windowed"      # the usual title bar and frame, freely resizable
BORDERLESS = "Borderless"  # no title bar or frame; resizable, optionally fullscreen
FIXED = "Fixed"            # the reference-shaped window, not resizable

MODES = [WINDOWED, BORDERLESS, FIXED]
DEFAULT_MODE = WINDOWED
