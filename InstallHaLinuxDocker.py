#!/usr/bin/env python3
"""
Install a deployment-ready Home Assistant (Container) stack on Debian/Ubuntu using Docker Compose.

Includes:
- Home Assistant (host network)
- Mosquitto (MQTT broker, password protected)
- Zigbee2MQTT (TCP coordinator, e.g. SLZB-06M)
- Node-RED
- code-server (password protected)

Behavior:
- Installs Docker Engine + compose plugin if missing
- Creates required directories under stack root
- Preserves existing config files unless --force-config-overwrite is used
- Creates Mosquitto password file
- Opens firewall ports when UFW is installed and enabled
- Starts the stack with docker compose

Example:
  sudo python3 InstallHaLinuxDocker_v2.py \
      --slzb-tcp tcp://10.160.0.231:6638 \
      --mqtt-user hass \
      --mqtt-password 'StrongMQTTPassword!' \
      --code-server-password 'StrongCodePassword!'
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import stat
import subprocess
from pathlib import Path
from textwrap import dedent

STACK_ROOT_DEFAULT = "/opt/stacks/hass"
DEFAULT_PORTS = [8123, 1883, 8080, 1880, 8443]


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    print(f"\n>>> {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )


def is_root() -> bool:
    return os.geteuid() == 0


def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def write_file(path: Path, content: str, mode: int | None = None, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        print(f"Preserved existing file: {path}")
        return
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    print(f"Written: {path}")


def backup_file(path: Path) -> None:
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        print(f"Backup created: {backup}")


def install_docker_debian_ubuntu() -> None:
    run(["apt-get", "update"])
    run([
        "apt-get", "install", "-y",
        "ca-certificates", "curl", "gnupg", "lsb-release",
        "apt-transport-https", "software-properties-common",
    ])

    if command_exists("docker"):
        print("Docker already installed; skipping docker engine installation.")
    else:
        run(["apt-get", "install", "-y", "docker.io"])

    compose_installed = False
    for pkg in ["docker-compose-v2", "docker-compose-plugin", "docker-compose"]:
        result = run(["apt-get", "install", "-y", pkg], check=False)
        if result.returncode == 0:
            print(f"Installed compose package: {pkg}")
            compose_installed = True
            break

    if not compose_installed:
        print(
            "WARNING: Could not install a Docker Compose package from the current repositories.\n"
            "The script will continue and try to use any existing compose command."
        )

    run(["systemctl", "enable", "--now", "docker"])

    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        run(["usermod", "-aG", "docker", sudo_user], check=False)
        print(
            f"NOTE: Added user '{sudo_user}' to docker group. "
            "Log out/in or reboot before using docker without sudo."
        )


def ensure_dirs(stack_root: Path) -> None:
    for path in [
        stack_root / "hass-config",
        stack_root / "mosquitto" / "config",
        stack_root / "mosquitto" / "data",
        stack_root / "mosquitto" / "log",
        stack_root / "zigbee2mqtt" / "data",
        stack_root / "nodered",
        stack_root / "code-server",
    ]:
        path.mkdir(parents=True, exist_ok=True)
        print(f"Ensured directory: {path}")


def ensure_network_tools() -> None:
    packages = []
    if not command_exists("openssl"):
        packages.append("openssl")
    if not command_exists("ufw"):
        # Optional, but nice to have on Ubuntu. Install only if missing.
        packages.append("ufw")
    if packages:
        run(["apt-get", "update"])
        run(["apt-get", "install", "-y", *packages])


def hash_mosquitto_password(password: str) -> str:
    result = run(["openssl", "passwd", "-6", password], capture=True)
    hashed = result.stdout.strip()
    if not hashed:
        raise SystemExit("Failed to generate password hash with openssl.")
    return hashed


def write_mosquitto_password_file(stack_root: Path, username: str, password: str, overwrite: bool) -> None:
    passwd_file = stack_root / "mosquitto" / "config" / "passwd"
    if passwd_file.exists() and not overwrite:
        print(f"Preserved existing Mosquitto password file: {passwd_file}")
        return
    hashed = hash_mosquitto_password(password)
    passwd_file.write_text(f"{username}:{hashed}\n", encoding="utf-8")
    passwd_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"Written: {passwd_file}")


def write_mosquitto_conf(stack_root: Path, enable_websockets: bool, overwrite: bool) -> None:
    listeners = dedent("""\
        listener 1883
        protocol mqtt
    """)
    if enable_websockets:
        listeners += "\nlistener 9001\nprotocol websockets\n"

    conf = dedent(f"""\
        persistence true
        persistence_location /mosquitto/data/

        log_dest stdout

        {listeners.strip()}

        allow_anonymous false
        password_file /mosquitto/config/passwd
    """) + "\n"

    write_file(
        stack_root / "mosquitto" / "config" / "mosquitto.conf",
        conf,
        overwrite=overwrite,
    )


def write_z2m_conf(stack_root: Path, slzb_tcp: str, adapter: str, mqtt_user: str, mqtt_password: str, overwrite: bool) -> None:
    conf = dedent(f"""\
        homeassistant:
          enabled: true

        frontend:
          enabled: true

        mqtt:
          server: mqtt://mosquitto:1883
          user: {mqtt_user}
          password: {mqtt_password}

        serial:
          port: {slzb_tcp}
          adapter: {adapter}

        advanced:
          log_level: info

        version: 5
    """)
    write_file(
        stack_root / "zigbee2mqtt" / "data" / "configuration.yaml",
        conf,
        overwrite=overwrite,
    )


def write_env_file(stack_root: Path, code_server_password: str, overwrite: bool) -> None:
    env_path = stack_root / ".env"
    env_content = dedent(f"""\
        CODE_SERVER_PASSWORD={code_server_password}
    """)
    write_file(env_path, env_content, mode=0o600, overwrite=overwrite)


def write_compose_yaml(stack_root: Path, tz: str, enable_websockets: bool, overwrite: bool) -> None:
    mosquitto_ports = ['      - "1883:1883"\n']
    if enable_websockets:
        mosquitto_ports.append('      - "9001:9001"\n')

    compose = (
        "services:\n"
        "  homeassistant:\n"
        "    container_name: homeassistant\n"
        "    image: ghcr.io/home-assistant/home-assistant:stable\n"
        "    restart: unless-stopped\n"
        "    privileged: true\n"
        "    network_mode: host\n"
        "    environment:\n"
        f"      - TZ={tz}\n"
        "    volumes:\n"
        "      - ./hass-config:/config\n"
        "      - /etc/localtime:/etc/localtime:ro\n"
        "      - /etc/timezone:/etc/timezone:ro\n"
        "      - /run/dbus:/run/dbus:ro\n"
        "\n"
        "  mosquitto:\n"
        "    container_name: mosquitto\n"
        "    image: eclipse-mosquitto:2\n"
        "    restart: unless-stopped\n"
        "    environment:\n"
        f"      - TZ={tz}\n"
        "    ports:\n"
        + "".join(mosquitto_ports) +
        "    volumes:\n"
        "      - ./mosquitto/config:/mosquitto/config\n"
        "      - ./mosquitto/data:/mosquitto/data\n"
        "      - ./mosquitto/log:/mosquitto/log\n"
        "      - /etc/localtime:/etc/localtime:ro\n"
        "      - /etc/timezone:/etc/timezone:ro\n"
        "\n"
        "  zigbee2mqtt:\n"
        "    container_name: zigbee2mqtt\n"
        "    image: koenkk/zigbee2mqtt:latest\n"
        "    restart: unless-stopped\n"
        "    depends_on:\n"
        "      - mosquitto\n"
        "    environment:\n"
        f"      - TZ={tz}\n"
        "    ports:\n"
        '      - "8080:8080"\n'
        "    volumes:\n"
        "      - ./zigbee2mqtt/data:/app/data\n"
        "      - /etc/localtime:/etc/localtime:ro\n"
        "      - /etc/timezone:/etc/timezone:ro\n"
        "\n"
        "  nodered:\n"
        "    container_name: nodered\n"
        "    image: nodered/node-red:latest\n"
        "    restart: unless-stopped\n"
        "    depends_on:\n"
        "      - mosquitto\n"
        "    environment:\n"
        f"      - TZ={tz}\n"
        "    ports:\n"
        '      - "1880:1880"\n'
        "    volumes:\n"
        "      - ./nodered:/data\n"
        "      - /etc/localtime:/etc/localtime:ro\n"
        "      - /etc/timezone:/etc/timezone:ro\n"
        "\n"
        "  code-server:\n"
        "    container_name: code_server\n"
        "    image: lscr.io/linuxserver/code-server:latest\n"
        "    restart: unless-stopped\n"
        "    environment:\n"
        f"      - TZ={tz}\n"
        "      - DEFAULT_WORKSPACE=/config\n"
        "      - PASSWORD=${CODE_SERVER_PASSWORD}\n"
        "    ports:\n"
        '      - "8443:8443"\n'
        "    volumes:\n"
        "      - ./hass-config:/config\n"
        "      - /etc/localtime:/etc/localtime:ro\n"
        "      - /etc/timezone:/etc/timezone:ro\n"
    )
    write_file(stack_root / "compose.yaml", compose, overwrite=overwrite)


def ufw_is_active() -> bool:
    if not command_exists("ufw"):
        return False
    result = run(["ufw", "status"], check=False, capture=True)
    return "Status: active" in result.stdout


def open_firewall_ports(enable_websockets: bool) -> None:
    if not ufw_is_active():
        print("UFW not active; skipping firewall changes.")
        return

    ports = DEFAULT_PORTS.copy()
    if enable_websockets:
        ports.append(9001)

    for port in ports:
        run(["ufw", "allow", str(port)], check=False)


def docker_compose_cmd() -> list[str]:
    result = run(["docker", "compose", "version"], check=False, capture=True)
    if result.returncode == 0:
        return ["docker", "compose"]

    if command_exists("docker-compose"):
        return ["docker-compose"]

    raise SystemExit(
        "No Docker Compose command found. Install docker-compose-v2, "
        "docker-compose-plugin, or docker-compose."
    )


def docker_compose_up(stack_root: Path) -> None:
    compose_cmd = docker_compose_cmd()
    run(compose_cmd + ["-f", str(stack_root / "compose.yaml"), "pull"], check=False)
    run(compose_cmd + ["-f", str(stack_root / "compose.yaml"), "up", "-d"])
    run(compose_cmd + ["-f", str(stack_root / "compose.yaml"), "ps"], check=False)


def validate_args(args: argparse.Namespace) -> None:
    if not args.slzb_tcp.startswith(("tcp://", "socket://")):
        raise SystemExit("--slzb-tcp must start with tcp:// or socket://")
    if len(args.mqtt_password) < 12:
        raise SystemExit("Use an MQTT password with at least 12 characters.")
    if len(args.code_server_password) < 12:
        raise SystemExit("Use a code-server password with at least 12 characters.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Home Assistant stack (Docker Compose).")
    parser.add_argument("--stack-root", default=STACK_ROOT_DEFAULT, help="Stack root directory.")
    parser.add_argument("--slzb-tcp", required=True,
                        help="TCP serial URL for coordinator, e.g. tcp://10.160.0.231:6638")
    parser.add_argument("--tz", default="Europe/Copenhagen", help="Timezone")
    parser.add_argument("--z2m-adapter", default="ezsp",
                        help="Zigbee2MQTT adapter: ezsp (older Silabs fw) or ember (newer).")
    parser.add_argument("--enable-websockets", action="store_true",
                        help="Expose Mosquitto websockets on port 9001.")
    parser.add_argument("--skip-docker-install", action="store_true",
                        help="Skip Docker installation step.")
    parser.add_argument("--mqtt-user", default="hass", help="Mosquitto username.")
    parser.add_argument("--mqtt-password", default=secrets.token_urlsafe(18),
                        help="Mosquitto password. Default: generated automatically.")
    parser.add_argument("--code-server-password", default=secrets.token_urlsafe(18),
                        help="Password for code-server. Default: generated automatically.")
    parser.add_argument("--force-config-overwrite", action="store_true",
                        help="Overwrite existing config files instead of preserving them.")
    args = parser.parse_args()

    if not is_root():
        raise SystemExit("ERROR: Run this script as root (e.g. sudo python3 InstallHaLinuxDocker_v2.py ...)")

    validate_args(args)
    stack_root = Path(args.stack_root)

    if not args.skip_docker_install:
        install_docker_debian_ubuntu()
    else:
        print("Skipping Docker install as requested.")
        run(["systemctl", "enable", "--now", "docker"], check=False)

    ensure_network_tools()
    ensure_dirs(stack_root)
    write_env_file(stack_root, args.code_server_password, overwrite=args.force_config_overwrite)
    write_mosquitto_password_file(
        stack_root, args.mqtt_user, args.mqtt_password, overwrite=args.force_config_overwrite
    )
    write_mosquitto_conf(stack_root, enable_websockets=args.enable_websockets,
                         overwrite=args.force_config_overwrite)
    write_z2m_conf(
        stack_root,
        slzb_tcp=args.slzb_tcp,
        adapter=args.z2m_adapter,
        mqtt_user=args.mqtt_user,
        mqtt_password=args.mqtt_password,
        overwrite=args.force_config_overwrite,
    )
    write_compose_yaml(stack_root, tz=args.tz, enable_websockets=args.enable_websockets,
                       overwrite=args.force_config_overwrite)
    open_firewall_ports(enable_websockets=args.enable_websockets)
    docker_compose_up(stack_root)

    print("\nDONE.\n")
    print("Access URLs:")
    print("- Home Assistant UI:   http://<host-ip>:8123")
    print("- Zigbee2MQTT UI:      http://<host-ip>:8080")
    print("- Node-RED UI:         http://<host-ip>:1880")
    print("- code-server UI:      https://<host-ip>:8443")
    print("\nCredentials:")
    print(f"- MQTT user:           {args.mqtt_user}")
    print(f"- MQTT password:       {args.mqtt_password}")
    print(f"- code-server password:{args.code_server_password}")
    print("\nHome Assistant:")
    print("- Because HA uses host networking, set MQTT broker host to 127.0.0.1 and port 1883 in the HA UI.")
    print("\nLogs:")
    print(f"- docker compose -f {stack_root/'compose.yaml'} logs -f mosquitto")
    print(f"- docker compose -f {stack_root/'compose.yaml'} logs -f zigbee2mqtt")
    print(f"- docker compose -f {stack_root/'compose.yaml'} logs -f homeassistant")


if __name__ == "__main__":
    main()
