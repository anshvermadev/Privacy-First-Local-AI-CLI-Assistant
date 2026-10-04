"""Owner-only state. Never apply ACL changes to an arbitrary parent directory."""
import os
from pathlib import Path
import stat
import subprocess
from .models import SafeError

MARKER = ".local-ai-state"


def secure(path):
    path = Path(path)
    if path.is_symlink():
        raise SafeError("State paths must not be symbolic links.", "UNSAFE_PATH")
    if os.name == "nt":
        identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True)
        import csv
        sid = next(csv.reader([identity.stdout.strip()]))[1]
        grant = "*" + sid + (":(OI)(CI)F" if path.is_dir() else ":F")
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", grant], capture_output=True, check=True)
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def check_state(root):
    root = Path(root)
    if root.is_symlink() or not (root / MARKER).is_file():
        raise SafeError("Not an initialized local-ai data directory. Run init first.", "NOT_INITIALIZED")
    if any(p.is_symlink() for p in root.iterdir()):
        raise SafeError("State directory contains symbolic links.", "UNSAFE_PATH")
    return root


def permission_status(root):
    if os.name == "nt":
        # Inspect the protected flag and access rules without parsing localized icacls output.
        import base64
        script = "$ErrorActionPreference='Stop'; $a=[System.IO.{kind}]::GetAccessControl('{path}'); $u=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; if(-not $a.AreAccessRulesProtected){{exit 1}}; foreach($r in $a.Access){{if($r.AccessControlType -eq 'Allow' -and $r.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -ne $u){{exit 1}}}}"
        for p in [root, *root.iterdir()]:
            command = script.format(path=str(p).replace("'", "''"), kind="Directory" if p.is_dir() else "File")
            encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True)
            if result.returncode:
                return False
        return True
    return all(not (stat.S_IMODE(p.stat().st_mode) & 0o077) for p in [root, *root.iterdir()])
