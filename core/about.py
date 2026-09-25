# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi

# Legal text, licenses, and program version.

import os
import sys

REPO_URL = "https://github.com/YezanSmadi/LlamaMXD"
ISSUES_URL = REPO_URL + "/issues"
LICENSE_NAME = "GPL-3.0-or-later"
COPYRIGHT = "Copyright © 2026 Yezan Smadi"
# Pak the Llama is the mascot (represented in the logo)
MASCOT_NAME = "Pak the Llama"
# The logo art itself is copyrighted separately from the GPL notice below: the GPL licenses the
# program's source code, not its visual identity, so LlamaMXD-Logo.svg is kept out of that grant
# (see licenses/README.txt).
LOGO_COPYRIGHT_NOTICE = (f"Logo and brand assets {COPYRIGHT}, all rights reserved. Brand assets may not "
                         "be copied, modified, or used in third-party projects or unofficial builds without "
                         "permission."
                         )
TRADEMARK_NOTICE = f"LlamaMXD™ and {MASCOT_NAME}™ are trademarks of Yezan Smadi."
NOTICE = (
    f"LlamaMXD™ {COPYRIGHT}\n\n"
    "This program is free software: you can redistribute it and/or modify it under the terms of the GNU "
    "General Public License as published by the Free Software Foundation, either version 3 of the License, "
    "or (at your option) any later version.\n\n"
    "This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even "
    "the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public "
    "License for more details.\n\n"
    "You should have received a copy of the GNU General Public License along with this program. If not, see "
    "https://www.gnu.org/licenses/."
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find(name):
    #Path of `name` beside a frozen app's exe (where the installer puts it), else in the repo root;
    #None if it isn't in either.
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    roots.append(_REPO_ROOT)
    for root in roots:
        path = os.path.join(root, name)
        if os.path.exists(path):
            return path
    return None


def license_path():
        # The project's full license text or None if it isn't there.
        return _find("LICENSE.txt") 


def licenses_dir():
    # The folder holding the third-party license texts (`licenses/`), or None if it isn't there.
    path = _find("licenses")
    return path if path and os.path.isdir(path) else None
