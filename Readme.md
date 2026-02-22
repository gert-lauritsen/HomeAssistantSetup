# Home Assistant Docker + Zigbee2MQTT (SLZB-06M)

This README documents a **working, stable Home Assistant setup using Docker**, with:

- Home Assistant (Container)
- Mosquitto (MQTT)
- Zigbee2MQTT
- SLZB-06M Ethernet Zigbee coordinator (EFR32 / EZSP)
- Optional: Node-RED, code-server

It reflects real-world troubleshooting and best practices.

---

## Architecture

```text
Zigbee devices
   ↓
SLZB-06M (Ethernet / TCP)
   ↓
Zigbee2MQTT (Docker)
   ↓ MQTT
Mosquitto (Docker)
   ↓
Home Assistant (Docker, host network)
```

Why this works well:
- No USB passthrough
- HA restarts don’t kill Zigbee
- Coordinator can be placed centrally

---

## Host requirements

- Debian / Ubuntu Linux
- Root or sudo access
- Wired Ethernet
- SLZB-06M reachable on LAN (e.g. `tcp://10.160.0.231:6638`)

---

## Directory layout

```text
/opt/stacks/hass/
├── compose.yaml
├── hass-config/
├── mosquitto/
│   ├── config/mosquitto.conf
│   ├── data/
│   └── log/
├── zigbee2mqtt/
│   └── data/configuration.yaml
├── nodered/
└── code-server/
```

---

## Docker Compose (`compose.yaml`)

```yaml
services:
  homeassistant:
    container_name: homeassistant
    image: ghcr.io/home-assistant/home-assistant:stable
    restart: unless-stopped
    privileged: true
    network_mode: host
    environment:
      - TZ=Europe/Copenhagen
    volumes:
      - ./hass-config:/config
      - /etc/localtime:/etc/localtime:ro
      - /run/dbus:/run/dbus:ro

  mosquitto:
    container_name: mosquitto
    image: eclipse-mosquitto:2
    restart: unless-stopped
    environment:
      - TZ=Europe/Copenhagen
    ports:
      - "1883:1883"
      - "9001:9001"
    volumes:
      - ./mosquitto/config:/mosquitto/config
      - ./mosquitto/data:/mosquitto/data
      - ./mosquitto/log:/mosquitto/log

  zigbee2mqtt:
    container_name: zigbee2mqtt
    image: koenkk/zigbee2mqtt:latest
    restart: unless-stopped
    depends_on:
      - mosquitto
    environment:
      - TZ=Europe/Copenhagen
    ports:
      - "8080:8080"
    volumes:
      - ./zigbee2mqtt/data:/app/data
      - /etc/localtime:/etc/localtime:ro

  nodered:
    container_name: nodered
    image: nodered/node-red:latest
    restart: unless-stopped
    depends_on:
      - mosquitto
    environment:
      - TZ=Europe/Copenhagen
    ports:
      - "1880:1880"
    volumes:
      - ./nodered:/data

  code-server:
    container_name: code_server
    image: lscr.io/linuxserver/code-server:latest
    restart: unless-stopped
    environment:
      - TZ=Europe/Copenhagen
      - DEFAULT_WORKSPACE=/config
    ports:
      - "8443:8443"
    volumes:
      - ./hass-config:/config
```

---

## Mosquitto configuration (`mosquitto.conf`)

```conf
persistence true
persistence_location /mosquitto/data/

log_dest stdout

listener 1883
protocol mqtt

listener 9001
protocol websockets

allow_anonymous true
```

Notes:
- Logging to stdout avoids file permission issues
- WebSockets (9001) optional

---

## Zigbee2MQTT configuration (`configuration.yaml`)

```yaml
homeassistant:
  enabled: true

frontend:
  enabled: true

mqtt:
  server: mqtt://mosquitto:1883

serial:
  port: tcp://10.160.0.231:6638
  adapter: ezsp

version: 5
```

### Important
- `adapter: ezsp` is required for **EZSP v12 (Silabs firmware 7.3.x)**
- Do **not** use `ember` unless firmware is upgraded to EZSP v13+

---

## Starting the stack

```bash
cd /opt/stacks/hass
sudo docker compose up -d
```

Check logs:

```bash
sudo docker compose logs -f mosquitto
sudo docker compose logs -f zigbee2mqtt
```

---

## Web interfaces

- Home Assistant: `http://<host-ip>:8123`
- Zigbee2MQTT: `http://<host-ip>:8080`
- Node-RED: `http://<host-ip>:1880`
- code-server: `https://<host-ip>:8443`

---

## Home Assistant MQTT integration

Because Home Assistant runs in **host network mode**:

- Broker: `127.0.0.1`
- Port: `1883`

Do **not** use `mosquitto` as hostname inside HA.

---

## Pairing Zigbee devices

1. Open Zigbee2MQTT UI
2. Enable **Permit join**
3. Reset device and pair
4. Rename device in Zigbee2MQTT **before** using it in HA

---

## IKEA remotes & dimmers (important)

Models:
- E2001 / E2002 / E2313 (buttons)
- E1524 / E1810 (dimmers)

Behavior:
- No button entities in HA
- They send **`action` events**
- Use **Device → Action triggers** in automations

Example trigger:
```yaml
trigger:
  - platform: device
    domain: mqtt
    device_id: <DEVICE_ID>
    type: action
    subtype: toggle
```

---

## IKEA devices stop working overnight

This is (when you search a ) normal behavior caused by:
- Deep sleep
- Weak or unstable Zigbee parent router

### Fix
- Ensure powered Zigbee routers nearby (IKEA plug or bulb)
- Re-pair close to router
- Avoid relying on coordinator alone
- not that I had any luck with it

---

## Recommended Zigbee buttons (more stable than IKEA)

- Aqara Wireless Mini / Dual Switch
- Aqara Cube
- Sengled Smart Button
- Philips Hue Smart Button (best with Hue bridge)

---

## Firmware notes (SLZB-06M)

Current confirmed firmware:
- Chip: EFR32
- Protocol: EZSP v12
- Version: 7.3.1.0

Upgrade firmware **only if you want to move to `adapter: ember`**.

---
## Anydesk
To have remote control install anydesk


Run it

Save as setup_anydesk_unattended.py, then:
```
sudo python3 setup_anydesk_unattended.py --user gert --enable-autologin --enable-ssh
sudo reboot
```
After reboot:
```
echo $XDG_SESSION_TYPE
anydesk
```

Then set the unattended password in the GUI.


---

## Common pitfalls

| Problem | Cause |
|------|------|
| Zigbee2MQTT won’t start | Wrong adapter (`ember` vs `ezsp`) |
| HA can’t connect MQTT | Using `mosquitto` instead of `127.0.0.1` |
| IKEA buttons stop | Sleep / routing issue |
| Ugly entity IDs | Renamed too late |

---

## Status

This setup is:
- Proven working
- Restart-safe
- Upgradeable
- Suitable for long-term use

---



