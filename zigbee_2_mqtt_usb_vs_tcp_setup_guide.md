# Zigbee2MQTT Setup: USB Dongle vs TCP (SLZB)

## Overview
This guide explains how to configure Zigbee2MQTT when using either:

- A **network-based Zigbee coordinator** (e.g. SLZB-06M)
- A **USB Zigbee dongle** (e.g. Sonoff, ConBee)

---

# 🔌 USB Dongle Setup

## Basic Configuration

Instead of:

```yaml
serial:
  port: tcp://10.160.0.231:6638
```

Use:

```yaml
serial:
  port: /dev/ttyUSB0
```

---

## ⚠️ Docker Requirement: Device Passthrough

You must expose the USB device to the container:

```yaml
devices:
  - /dev/ttyUSB0:/dev/ttyUSB0
```

Without this, Zigbee2MQTT cannot access the dongle.

---

## 🔍 Find Correct Device

Run:

```bash
ls /dev/ttyUSB*
ls /dev/ttyACM*
```

Typical results:

| Device | Path |
|--------|------|
| Sonoff | /dev/ttyUSB0 |
| ConBee | /dev/ttyACM0 |

---

## 🔧 Recommended: Stable Device Path

Use persistent device naming:

```bash
ls -l /dev/serial/by-id/
```

Example:

```bash
/dev/serial/by-id/usb-ITead_Sonoff_Zigbee_3.0_Dongle_Plus_123456-if00-port0
```

Then configure:

```yaml
serial:
  port: /dev/serial/by-id/usb-ITead_Sonoff_...
```

Docker:

```yaml
devices:
  - /dev/serial/by-id/usb-ITead_Sonoff_...:/dev/ttyUSB0
```

---

## ⚠️ Permissions

Add user to dialout group:

```bash
sudo usermod -aG dialout $USER
```

Optional (quick test):

```bash
sudo chmod 666 /dev/ttyUSB0
```

---

## 🔧 Adapter Setting

| Device | Adapter |
|--------|--------|
| Sonoff (new firmware) | ember |
| Sonoff (old firmware) | ezsp |
| ConBee | deconz |

---

# 🌐 TCP (SLZB) Setup

## Configuration

```yaml
serial:
  port: tcp://10.160.0.231:6638
  adapter: ezsp
```

## Notes

- No Docker device mapping required
- More stable for remote setups
- Easier deployment

---

# 🔧 Script Logic (Recommended)

## Arguments

```python
parser.add_argument("--slzb-tcp")
parser.add_argument("--serial-port")
```

## Selection Logic

```python
if args.slzb_tcp:
    port = args.slzb_tcp
elif args.serial_port:
    port = args.serial_port
else:
    raise SystemExit("You must specify either --slzb-tcp or --serial-port")
```

## Docker Device Mapping (USB only)

```python
if args.serial_port and args.serial_port.startswith("/dev"):
    compose += f"""
    devices:
      - {args.serial_port}:{args.serial_port}
    """
```

---

# ✔️ Summary

| Setup Type | Configuration |
|-----------|-------------|
| TCP (SLZB) | tcp://IP:PORT |
| USB Dongle | /dev/ttyUSB0 |

---

# ⭐ Recommendation

| Option | Stability | Complexity |
|------|--------|------------|
| SLZB (network) | ⭐⭐⭐⭐⭐ | ⭐ |
| USB dongle | ⭐⭐⭐ | ⭐⭐⭐ |

👉 Use **TCP-based coordinator** if possible.
👉 Use **USB** if local hardware is required.

---

# 🚀 Optional Improvements

- Auto-detect USB dongle
- Auto-select adapter
- Fallback between TCP and USB

