#!/usr/bin/env python3
"""Make the sign-in code for the dashboard.

  python pipeline/make_login.py USERNAME PASSWORD

Paste the line it prints over the  var HASH='...'  line near the bottom of site/index.html.
The sign-in keeps casual visitors out. It is not strong protection: the totals file
(site/data.json) can still be opened by anyone who knows its address.
"""
import hashlib, sys
if len(sys.argv) != 3:
    sys.exit(__doc__)
user, pw = sys.argv[1].strip().lower(), sys.argv[2]
print("var HASH='%s';" % hashlib.sha256(f"{user}:{pw}".encode()).hexdigest())
