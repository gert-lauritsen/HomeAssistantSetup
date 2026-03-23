#!/usr/bin/env python3
"""
Ubuntu AnyDesk unattended access helper

What it does:
- Disables Wayland (forces Xorg) in /etc/gdm3/custom.conf
- Optionally enables GDM auto-login for a specified user
- Detects the correct AnyDesk systemd service and enables + starts it
- Optionally installs openssh-server and enables ssh

Usage:
  sudo python3 InstallAnyDesk.py --user gert --enable-autologin --enable-ssh

Notes:
- If AnyDesk is not installed, the script will add the official AnyDesk APT repository and install it.
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


def run(cmd: list[str], check: bool = True, capture_output: bool = False) -> subprocess.CompletedProcess:
    print(f"+ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("This script must be run as root. Use: sudo python3 InstallAnyDesk.py ...")


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
        if not conf.endswith("\n"):
            conf += "\n"
        conf += f"\n[{section}]\n{key}={value}\n"
        return conf

    start = match.end()
    next_section = re.search(r"^\[.+?\]\s*$", conf[start:], flags=re.MULTILINE)
    end = start + (next_section.start() if next_section else len(conf[start:]))

    block = conf[start:end]

    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=\s*.*$", re.MULTILINE)
    if key_re.search(block):
        block = key_re.sub(f"{key}={value}", block, count=1)
    else:
        if not block.endswith("\n"):
            block += "\n"
        block += f"{key}={value}\n"

    return conf[:start] + block + conf[end:]


def disable_wayland_in_gdm() -> None:
    backup_file(GDM_CUSTOM_CONF)
    conf = GDM_CUSTOM_CONF.read_text(encoding="utf-8", errors="replace")
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


def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def service_exists(service: str) -> bool:
    result = run(["systemctl", "list-unit-files", service], check=False, capture_output=True)
    stdout = result.stdout or ""
    return service in stdout


def find_anydesk_service() -> str | None:
    candidates = [
        "anydesk.service",
        "anydesk",
    ]

    for service in candidates:
        if service_exists(service):
            return service

    result = run(["systemctl", "list-unit-files"], check=False, capture_output=True)
    stdout = result.stdout or ""
    for line in stdout.splitlines():
        unit = line.split()[0] if line.split() else ""
        if "anydesk" in unit.lower() and unit.endswith(".service"):
            return unit

    return None


def systemctl_enable_start(service: str) -> None:
    if not service_exists(service):
        raise SystemExit(
            f"Systemd service '{service}' was not found. "
            "Check whether the package is installed and what the actual unit name is."
        )

    run(["systemctl", "enable", service])
    run(["systemctl", "start", service])
    run(["systemctl", "status", service, "--no-pager"], check=False)


def apt_install(pkgs: list[str]) -> None:
    run(["apt-get", "update"])
    run(["apt-get", "install", "-y"] + pkgs)


def install_anydesk() -> None:
    print("== Installing AnyDesk ==")

    apt_install(["ca-certificates", "curl", "apt-transport-https"])
    run(["install", "-m", "0755", "-d", "/etc/apt/keyrings"])
    run(["curl", "-fsSL", "https://keys.anydesk.com/repos/DEB-GPG-KEY", "-o", "/etc/apt/keyrings/keys.anydesk.com.asc"])
    run(["chmod", "a+r", "/etc/apt/keyrings/keys.anydesk.com.asc"])
    run(["bash", "-lc", 'echo "deb [signed-by=/etc/apt/keyrings/keys.anydesk.com.asc] https://deb.anydesk.com all main" > /etc/apt/sources.list.d/anydesk-stable.list'])
    apt_install(["anydesk"])


def ensure_anydesk_running() -> None:
    if not command_exists("anydesk"):
        install_anydesk()

    service = find_anydesk_service()
    if not service:
        raise SystemExit(
            "AnyDesk appears to be installed, but no matching systemd unit was found.\n"
            "Run this to inspect available units:\n"
            "  systemctl list-unit-files | grep -i anydesk"
        )

    print(f"Using AnyDesk service: {service}")
    systemctl_enable_start(service)


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
            "If you use LightDM/SDDM, the script must be adapted."
        )

    print("== Configuring GDM to use Xorg (disable Wayland) ==")
    disable_wayland_in_gdm()

    if args.enable_autologin:
        print("== Enabling GDM auto-login ==")
        enable_gdm_autologin(args.user)
    else:
        print("== Skipping auto-login (not requested) ==")

    print("== Ensuring AnyDesk service is enabled and running ==")
    ensure_anydesk_running()

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
