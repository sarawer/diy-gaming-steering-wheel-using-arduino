import argparse
import ctypes
import sys
import time

import serial
from serial.tools import list_ports

MAX_STEERING_DEGREES = 450
BAUD_RATE = 9600
DEFAULT_LINUX_PORT = "/dev/ttyACM0"


class LinuxGamepad:
    def __init__(self):
        try:
            from evdev import AbsInfo, UInput, ecodes
        except ImportError as exc:
            raise RuntimeError(
                "Linux needs evdev installed in this Python environment."
            ) from exc

        self.ecodes = ecodes
        self.button_codes = (ecodes.BTN_SOUTH, ecodes.BTN_EAST)
        capabilities = {
            ecodes.EV_ABS: [
                (
                    ecodes.ABS_X,
                    AbsInfo(
                        value=0,
                        min=-32768,
                        max=32767,
                        fuzz=0,
                        flat=0,
                        resolution=0,
                    ),
                )
            ],
            ecodes.EV_KEY: list(self.button_codes),
        }
        self.device = UInput(
            capabilities,
            name="DIY Steering Controller",
            version=1,
        )
        self.button_states = [0, 0]

    def update(self, steering_degrees, button1, button2):
        if steering_degrees < 0:
            axis_value = round(
                steering_degrees * 32768 / MAX_STEERING_DEGREES
            )
        else:
            axis_value = round(
                steering_degrees * 32767 / MAX_STEERING_DEGREES
            )

        self.device.write(
            self.ecodes.EV_ABS,
            self.ecodes.ABS_X,
            axis_value,
        )

        for index, (code, state) in enumerate(
            zip(self.button_codes, (button1, button2))
        ):
            if state != self.button_states[index]:
                self.device.write(self.ecodes.EV_KEY, code, state)
                self.button_states[index] = state

        self.device.syn()

    def close(self):
        self.device.close()


class WindowsVJoy:
    def __init__(self, device_id):
        try:
            import pyvjoy
        except ImportError as exc:
            raise RuntimeError(
                "Windows needs pyvjoy installed. Run: py -m pip install pyvjoy"
            ) from exc

        self.pyvjoy = pyvjoy
        try:
            self.device = pyvjoy.VJoyDevice(device_id)
        except Exception as exc:
            raise RuntimeError(
                f"Could not open vJoy device {device_id}. Enable that device "
                "in Configure vJoy, with X, Y, and Z axes and at least one "
                "button enabled."
            ) from exc
        self.get_async_key_state = ctypes.windll.user32.GetAsyncKeyState

    def keyboard_buttons_pressed(self):
        # vJoy button 1 = main keyboard 5 or numpad 5
        # vJoy button 2 = Up arrow
        # vJoy button 3 = Down arrow
        # vJoy button 4 = Space
        main_5_down = self.get_async_key_state(0x35) & 0x8000
        numpad_5_down = self.get_async_key_state(0x65) & 0x8000
        up_down = self.get_async_key_state(0x26) & 0x8000
        down_down = self.get_async_key_state(0x28) & 0x8000
        space_down = self.get_async_key_state(0x20) & 0x8000
        return (
            bool(main_5_down or numpad_5_down),
            bool(up_down),
            bool(down_down),
            bool(space_down),
        )

    def update(self, steering_degrees, button1, button2, keyboard_buttons=(False, False, False, False)):
        # vJoy axes use values from 0x0000 to 0x8000.
        axis_value = round(
            (steering_degrees + MAX_STEERING_DEGREES)
            * 0x8000
            / (2 * MAX_STEERING_DEGREES)
        )
        axis_value = max(0, min(0x8000, axis_value))

        if not self.device.set_axis(self.pyvjoy.HID_USAGE_X, axis_value):
            raise RuntimeError(
                "vJoy rejected the X axis value. Enable the X axis for the "
                "selected device in Configure vJoy."
            )
        # Button 1 acts as a digital throttle; button 2 acts as a digital brake.
        # Separate axes let Assetto Corsa bind each button as a pedal input.
        throttle_value = 0x8000 if button1 else 0x0000
        brake_value = 0x8000 if button2 else 0x0000
        if not self.device.set_axis(self.pyvjoy.HID_USAGE_Y, throttle_value):
            raise RuntimeError(
                "vJoy rejected the Y axis. Enable the Y axis for the selected "
                "device in Configure vJoy."
            )
        if not self.device.set_axis(self.pyvjoy.HID_USAGE_Z, brake_value):
            raise RuntimeError(
                "vJoy rejected the Z axis. Enable the Z axis for the selected "
                "device in Configure vJoy."
            )
        for button_id, pressed in enumerate(keyboard_buttons, start=1):
            if not self.device.set_button(button_id, pressed):
                raise RuntimeError(
                    f"vJoy rejected button {button_id}. Enable at least four "
                    "buttons for the selected device in Configure vJoy."
                )
    def close(self):
        self.device.reset()


def show_ports():
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return

    for port in ports:
        description = f" - {port.description}" if port.description else ""
        print(f"{port.device}{description}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Arduino steering wheel to Linux evdev or Windows vJoy."
    )
    parser.add_argument(
        "--port",
        help="Arduino serial port, for example COM5 or /dev/ttyACM0.",
    )
    parser.add_argument(
        "--vjoy-device",
        type=int,
        default=1,
        help="Windows vJoy device number (default: 1).",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List serial ports and exit.",
    )
    args = parser.parse_args()

    if args.list_ports:
        show_ports()
        raise SystemExit(0)

    if args.port:
        return args
    if sys.platform.startswith("linux"):
        args.port = DEFAULT_LINUX_PORT
        return args

    parser.error("On Windows, specify the Arduino port, such as --port COM5.")


def main():
    args = parse_args()

    if sys.platform == "win32":
        backend = WindowsVJoy(args.vjoy_device)
    elif sys.platform.startswith("linux"):
        backend = LinuxGamepad()
    else:
        raise SystemExit("This controller supports Fedora/Linux and Windows.")

    ser = None
    try:
        ser = serial.Serial(args.port, BAUD_RATE, timeout=1)
        print(f"Controller started on {args.port} at {BAUD_RATE} baud")
        print("Arduino format: signed_degrees,button1,button2")
        if sys.platform == "win32":
            print(
                "vJoy mapping: X=steering, Y=throttle (A0), Z=brake (A1); "
                "buttons 1-4 = 5, Up, Down, Space"
            )

        last_status_time = 0.0
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            fields = line.split(",")
            if len(fields) != 3:
                continue

            try:
                steering_degrees, button1, button2 = (
                    int(field) for field in fields
                )
            except ValueError:
                continue

            if (
                not -MAX_STEERING_DEGREES
                <= steering_degrees
                <= MAX_STEERING_DEGREES
                or button1 not in (0, 1)
                or button2 not in (0, 1)
            ):
                continue

            if sys.platform == "win32":
                backend.update(
                    steering_degrees,
                    button1,
                    button2,
                    keyboard_buttons=backend.keyboard_buttons_pressed(),
                )
            else:
                backend.update(steering_degrees, button1, button2)

            now = time.monotonic()
            if now - last_status_time >= 0.1:
                print(
                    f"Steering {steering_degrees:+4d} deg | "
                    f"Throttle {button1} | Brake {button2}"
                )
                last_status_time = now

    except KeyboardInterrupt:
        print("\nStopping controller...")
    finally:
        if ser is not None:
            ser.close()
        backend.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, serial.SerialException) as exc:
        raise SystemExit(str(exc)) from exc