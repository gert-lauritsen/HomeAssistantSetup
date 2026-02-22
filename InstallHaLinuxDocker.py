#!/usr/bin/env python3
"""
Install Home Assistant (Container) stack on Debian/Ubuntu using Docker Compose.

Includes:
- homeassistant (host network)
- mosquitto (MQTT broker)
- zigbee2mqtt (TCP coordinator e.g., SLZB-06M)
- nodered
- code-server

Tested assumptions:
- Debian/Ubuntu host with apt
- You want stack root: /opt/stacks/hass
- You have an SLZB-06M reachable via TCP (e.g. tcp://10.160.0.231:6638)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent


STACK_ROOT_DEFAULT = "/opt/stacks/hass"


def run(cmd: list[str], check: bool = True) -> None:
    print(f"\n>>> {' '.join(cmd)}")
    subprocess.run(cmd, check=check)


def is_root() -> bool:
    return os.geteuid() == 0


def write_file(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    print(f"Written: {path}")


def install_docker_debian_ubuntu() -> None:
    """
    Installs Docker Engine + compose plugin using Debian/Ubuntu packages.
    Uses distro packages (docker.io + docker-compose-plugin) for robustness.
    """
    run(["apt-get", "update"])
    run(["apt-get", "install", "-y",
         "ca-certificates", "curl", "gnupg", "lsb-release",
         "apt-transport-https", "software-properties-common"])

    # Use Ubuntu/Debian packages (simple and stable).
    run(["apt-get", "install", "-y", "docker.io", "docker-compose-plugin"])

    run(["systemctl", "enable", "--now", "docker"])

    # Add invoking user (SUDO_USER) to docker group if available
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        run(["usermod", "-aG", "docker", sudo_user], check=False)
        print(f"\nNOTE: Added user '{sudo_user}' to 'docker' group. "
              f"You must log out/in for it to take effect.")


def ensure_dirs(stack_root: Path) -> None:
    # Stack directories
    (stack_root / "hass-config").mkdir(parents=True, exist_ok=True)
    (stack_root / "mosquitto" / "config").mkdir(parents=True, exist_ok=True)
    (stack_root / "mosquitto" / "data").mkdir(parents=True, exist_ok=True)
    (stack_root / "mosquitto" / "log").mkdir(parents=True, exist_ok=True)
    (stack_root / "zigbee2mqtt" / "data").mkdir(parents=True, exist_ok=True)
    (stack_root / "nodered").mkdir(parents=True, exist_ok=True)
    (stack_root / "code-server").mkdir(parents=True, exist_ok=True)


def write_mosquitto_conf(stack_root: Path, enable_websockets: bool) -> None:
    if enable_websockets:
        conf = dedent("""\
            persistence true
            persistence_location /mosquitto/data/

            log_dest stdout

            listener 1883
            protocol mqtt

            listener 9001
            protocol websockets

            allow_anonymous true
        """)
    else:
        conf = dedent("""\
            persistence true
            persistence_location /mosquitto/data/

            log_dest stdout

            listener 1883
            protocol mqtt

            allow_anonymous true
        """)
    write_file(stack_root / "mosquitto" / "config" / "mosquitto.conf", conf)


def write_z2m_conf(stack_root: Path, slzb_tcp: str, adapter: str, tz: str) -> None:
    # Zigbee2MQTT configuration
    conf = dedent(f"""\
        homeassistant:
          enabled: true

        frontend:
          enabled: true

        mqtt:
          server: mqtt://mosquitto:1883

        serial:
          port: {slzb_tcp}
          adapter: {adapter}

        advanced:
          log_level: info

        # Keep version line to avoid migration confusion
        version: 5
    """)
    write_file(stack_root / "zigbee2mqtt" / "data" / "configuration.yaml", conf)


def write_compose_yaml(stack_root: Path, tz: str, enable_websockets: bool) -> None:
    # Expose websocket port only if enabled
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
        "\n"
        "  code-server:\n"
        "    container_name: code_server\n"
        "    image: lscr.io/linuxserver/code-server:latest\n"
        "    restart: unless-stopped\n"
        "    environment:\n"
        f"      - TZ={tz}\n"
        "      - DEFAULT_WORKSPACE=/config\n"
        "    ports:\n"
        '      - "8443:8443"\n'
        "    volumes:\n"
        "      - ./hass-config:/config\n"
    )
    write_file(stack_root / "compose.yaml", compose)


def docker_compose_up(stack_root: Path) -> None:
    # Use docker compose plugin
    run(["docker", "compose", "-f", str(stack_root / "compose.yaml"), "up", "-d"])


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
    args = parser.parse_args()

    if not is_root():
        raise SystemExit("ERROR: Run this script as root (e.g. sudo python3 install_ha_stack.py ...)")

    stack_root = Path(args.stack_root)

    if not args.skip_docker_install:
        install_docker_debian_ubuntu()
    else:
        print("Skipping Docker install as requested.")

    ensure_dirs(stack_root)
    write_mosquitto_conf(stack_root, enable_websockets=args.enable_websockets)
    write_z2m_conf(stack_root, slzb_tcp=args.slzb_tcp, adapter=args.z2m_adapter, tz=args.tz)
    write_compose_yaml(stack_root, tz=args.tz, enable_websockets=args.enable_websockets)

    docker_compose_up(stack_root)

    print("\nDONE.\n")
    print("Next steps:")
    print(f"- Home Assistant UI:   http://<host-ip>:8123")
    print(f"- Zigbee2MQTT UI:      http://<host-ip>:8080")
    print(f"- Node-RED UI:         http://<host-ip>:1880")
    print(f"- code-server UI:      https://<host-ip>:8443")
    print("\nHome Assistant (MQTT integration):")
    print("- Because HA uses host networking, set MQTT broker host to 127.0.0.1 and port 1883 in HA UI.\n")
    print("Logs:")
    print(f"- docker compose -f {stack_root/'compose.yaml'} logs -f mosquitto")
    print(f"- docker compose -f {stack_root/'compose.yaml'} logs -f zigbee2mqtt")


if __name__ == "__main__":
    main()