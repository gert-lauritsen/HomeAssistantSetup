#!/usr/bin/env python3
"""
Ubuntu AnyDesk unattended access helper

What it does:
- Disables Wayland (forces Xorg) in /etc/gdm3/custom.conf
- Optionally enables GDM auto-login for a specified user
- Enables + starts anydesk.service
- Optionally installs openssh-server and enables ssh

Usage:
  sudo python3 setup_anydesk_unattended.py --user gert --enable-autologin --enable-ssh

Notes:
- AnyDesk unattended password still needs to be set via AnyDesk GUI.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


GDM_CUSTOM_CONF = Path("/etc/gdm3/custom.conf")


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"+ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, text=True)


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("This script must be run as root. Use: sudo python3 setup_anydesk_unattended.py ...")


def backup_file(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Expected file does not exist: {path}")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak_{ts}")
    shutil.copy2(path, backup)
    print(f"Backed up {path} -> {backup}")
    return backup


def ensure_line_in_section(conf: str, section: str, key: str, value: str) -> str:
    """
    Ensure `key=value` exists inside [section]. Create section if missing.
    Replace existing key in that section if present.
    """
    section_re = re.compile(rf"^\[{re.escape(section)}\]\s*$", re.MULTILINE)
    match = section_re.search(conf)

    if not match:
        # Append section at end
        if not conf.endswith("\n"):
            conf += "\n"
        conf += f"\n[{section}]\n{key}={value}\n"
        return conf

    # Find the section block range
    start = match.end()
    # Find next section header or end of file
    next_section = re.search(r"^\[.+?\]\s*$", conf[start:], flags=re.MULTILINE)
    end = start + (next_section.start() if next_section else len(conf[start:]))

    block = conf[start:end]

    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=\s*.*$", re.MULTILINE)
    if key_re.search(block):
        block = key_re.sub(f"{key}={value}", block, count=1)
    else:
        # Ensure block ends with newline, then append
        if not block.endswith("\n"):
            block += "\n"
        block += f"{key}={value}\n"

    return conf[:start] + block + conf[end:]


def disable_wayland_in_gdm() -> None:
    backup_file(GDM_CUSTOM_CONF)
    conf = GDM_CUSTOM_CONF.read_text(encoding="utf-8", errors="replace")

    # In GDM, WaylandEnable=false is typically under [daemon], but it is accepted anywhere.
    conf2 = ensure_line_in_section(conf, "daemon", "WaylandEnable", "false")

    if conf2 != conf:
        GDM_CUSTOM_CONF.write_text(conf2, encoding="utf-8")
        print("Updated GDM config: Wayland disabled (WaylandEnable=false).")
    else:
        print("GDM config already has WaylandEnable=false (no change).")


def enable_gdm_autologin(user: str) -> None:
    backup_file(GDM_CUSTOM_CONF)
    conf = GDM_CUSTOM_CONF.read_text(encoding="utf-8", errors="replace")

    conf2 = conf
    conf2 = ensure_line_in_section(conf2, "daemon", "AutomaticLoginEnable", "true")
    conf2 = ensure_line_in_section(conf2, "daemon", "AutomaticLogin", user)

    if conf2 != conf:
        GDM_CUSTOM_CONF.write_text(conf2, encoding="utf-8")
        print(f"Updated GDM config: auto-login enabled for user '{user}'.")
    else:
        print("GDM auto-login settings already present (no change).")


def systemctl_enable_start(service: str) -> None:
    run(["systemctl", "enable", service])
    run(["systemctl", "start", service])
    run(["systemctl", "status", service, "--no-pager"], check=False)


def apt_install(pkgs: list[str]) -> None:
    run(["apt-get", "update"])
    run(["apt-get", "install", "-y"] + pkgs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure Ubuntu for AnyDesk unattended access (Xorg + optional auto-login).")
    parser.add_argument("--user", default="gert", help="Username for auto-login (default: gert)")
    parser.add_argument("--enable-autologin", action="store_true", help="Enable GDM auto-login for --user")
    parser.add_argument("--enable-ssh", action="store_true", help="Install + enable openssh-server as fallback access")
    parser.add_argument("--restart-gdm", action="store_true", help="Restart GDM (will log you out). Prefer reboot.")
    args = parser.parse_args()

    require_root()

    if not GDM_CUSTOM_CONF.exists():
        raise SystemExit(
            f"{GDM_CUSTOM_CONF} not found. This script assumes GDM (Ubuntu GNOME). "
            "If you use LightDM/SDDM, tell me and I’ll adapt it."
        )

    print("== Configuring GDM to use Xorg (disable Wayland) ==")
    disable_wayland_in_gdm()

    if args.enable_autologin:
        print("== Enabling GDM auto-login ==")
        enable_gdm_autologin(args.user)
    else:
        print("== Skipping auto-login (not requested) ==")

    print("== Ensuring AnyDesk service is enabled and running ==")
    systemctl_enable_start("anydesk.service")

    if args.enable_ssh:
        print("== Installing + enabling OpenSSH server ==")
        apt_install(["openssh-server"])
        systemctl_enable_start("ssh.service")
    else:
        print("== Skipping SSH setup (not requested) ==")

    if args.restart_gdm:
        print("== Restarting GDM (this will end your current GUI session) ==")
        run(["systemctl", "restart", "gdm3"])
        print("GDM restarted.")
    else:
        print("\n== Next step ==")
        print("Reboot is recommended to ensure Xorg is active:")
        print("  sudo reboot")

    print("\n== After reboot/login, verify ==")
    print("  echo $XDG_SESSION_TYPE    # should be: x11")
    print("  who                      # should show a logged-in session for the user")
    print("  anydesk --get-id         # shows the AnyDesk ID (if supported by your version)")

    print("\n== Finally, set Unattended Access password in AnyDesk GUI ==")
    print("  anydesk")
    print("  Settings → Security → Unattended Access → set password")
    print("\nDone.")


if __name__ == "__main__":
    main()