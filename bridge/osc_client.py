"""
Low-level OSC wrapper for AbletonOSC.

AbletonOSC listens on port 11000, replies on port 11001.
This module is imported by pull.py and device.py.
"""

import argparse
import socket
import threading
import time

from pythonosc import dispatcher, osc_server, udp_client
from pythonosc.osc_message_builder import OscMessageBuilder

ABLETON_OSC_HOST = "127.0.0.1"
ABLETON_OSC_SEND_PORT = 11000   # we send to this port (AbletonOSC listens here)
ABLETON_OSC_RECV_PORT = 11001   # we receive on this port (AbletonOSC replies here)

DEFAULT_TIMEOUT = 4.0  # seconds to wait for a reply


class OscClient:
    """Synchronous OSC client — send a message and block until reply arrives."""

    def __init__(self, host=ABLETON_OSC_HOST,
                 send_port=ABLETON_OSC_SEND_PORT,
                 recv_port=ABLETON_OSC_RECV_PORT):
        self._client = udp_client.SimpleUDPClient(host, send_port)
        self._recv_port = recv_port
        self._results = {}
        self._lock = threading.Lock()

        # Start reply server
        self._dispatcher = dispatcher.Dispatcher()
        self._dispatcher.set_default_handler(self._default_handler)
        self._server = osc_server.ThreadingOSCUDPServer(
            ("0.0.0.0", recv_port), self._dispatcher
        )
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _default_handler(self, address, *args):
        with self._lock:
            self._results[address] = list(args)

    def send(self, address, *args):
        """Send an OSC message. Returns immediately."""
        self._client.send_message(address, list(args))

    def query(self, send_address, recv_address, *args, timeout=DEFAULT_TIMEOUT):
        """Send a message and wait for a reply on recv_address."""
        with self._lock:
            self._results.pop(recv_address, None)

        self.send(send_address, *args)

        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if recv_address in self._results:
                    return self._results.pop(recv_address)
            time.sleep(0.01)

        raise TimeoutError(
            f"No reply on {recv_address} within {timeout}s. "
            "Is AbletonOSC running? Is the extension installed?"
        )

    def close(self):
        self._server.shutdown()

    # ----------------------------------------------------------------
    # Reply-prefix helpers
    #
    # AbletonOSC echoes the addressing args back at the head of every reply:
    # track-scoped handlers prepend (track_index), device-scoped handlers
    # prepend (track_index, device_index). Strip them so callers get values only.
    # ----------------------------------------------------------------

    def _track_query(self, address, track_index):
        result = self.query(address, address, track_index)
        return result[1:] if result else []

    def _device_query(self, address, track_index, device_index):
        result = self.query(address, address, track_index, device_index)
        return result[2:] if result else []

    # ----------------------------------------------------------------
    # Convenience helpers
    # ----------------------------------------------------------------

    def get_tempo(self):
        """Return current tempo as float."""
        result = self.query("/live/song/get/tempo", "/live/song/get/tempo")
        return result[0] if result else None

    def get_time_signature(self):
        """Return the song's global time signature as (numerator, denominator).

        Stock AbletonOSC exposes both as song properties. Unlike AbletonMCP's
        get_session_info, which CLAUDE.md flags as unreliable, these read straight off
        the Live song object.

        This is the *global* signature only. Live's arrangement can carry time-signature
        changes, and no OSC address exposes them, so a caller deriving bar numbers from
        this value is assuming one meter for the whole song. Returns None if either
        half does not come back.
        """
        num = self.query("/live/song/get/signature_numerator",
                         "/live/song/get/signature_numerator")
        den = self.query("/live/song/get/signature_denominator",
                         "/live/song/get/signature_denominator")
        if not num or not den:
            return None
        return int(num[0]), int(den[0])

    def get_track_names(self):
        """Return list of (index, name) for all tracks."""
        result = self.query("/live/song/get/track_names", "/live/song/get/track_names")
        return list(enumerate(result)) if result else []

    def get_arrangement_clips(self, track_index):
        """Return list of (start_time, length) for all arrangement clips on a track.

        Uses the extension's combined handler rather than stock AbletonOSC's separate
        /start_time and /length addresses. The stock pair costs two round trips per
        track and raises on Group tracks, which sends no reply at all and hangs the
        client for a full timeout. See abletonosc/arrangement_clip.py.
        """
        result = self.query("/live/arrangement_clip/get/clips",
                            "/live/arrangement_clip/get/clips",
                            track_index)
        # Handler echoes track_index, then interleaved (start_time, length).
        values = result[1:] if result else []
        if len(values) % 2 != 0:
            raise RuntimeError(
                f"Track {track_index}: arrangement clip reply has an odd value count "
                f"({len(values)}), expected interleaved (start_time, length) pairs."
            )
        return [(values[i], values[i + 1]) for i in range(0, len(values), 2)]

    def get_arrangement_clip_notes(self, track_index, clip_start_time):
        """Return flat note list [pitch, start, dur, vel, mute, ...] from extended handler."""
        result = self.query(
            "/live/arrangement_clip/get/notes",
            "/live/arrangement_clip/get/notes",
            track_index, float(clip_start_time)
        )
        # Handler echoes (track_index, clip_start_time) before the note data.
        return result[2:] if result else []

    def get_device_names(self, track_index):
        """Return list of device names on a track."""
        return self._track_query("/live/track/get/devices/name", track_index)

    def get_device_param_names(self, track_index, device_index):
        return self._device_query("/live/device/get/parameters/name",
                                  track_index, device_index)

    def get_device_param_values(self, track_index, device_index):
        return self._device_query("/live/device/get/parameters/value",
                                  track_index, device_index)

    def get_device_param_min(self, track_index, device_index):
        return self._device_query("/live/device/get/parameters/min",
                                  track_index, device_index)

    def get_device_param_max(self, track_index, device_index):
        return self._device_query("/live/device/get/parameters/max",
                                  track_index, device_index)

    def get_device_param_value_string(self, track_index, device_index, param_index):
        """Return the device's own display string for one parameter, e.g. '-40.0 dB'.

        This is what the plugin UI shows, via Live's str_for_value(), so it is
        authoritative for real UI units. Unlike the batch /parameters/* addresses
        this is one round trip per parameter, so use it per-device, not per-session.
        Returns None if the device does not supply a string for that parameter.
        """
        result = self.query("/live/device/get/parameter/value_string",
                            "/live/device/get/parameter/value_string",
                            track_index, device_index, int(param_index))
        # Reply is (track_index, device_index, param_index, value_string).
        return result[3] if result and len(result) > 3 else None


def check_connection():
    """Quick connectivity test. Returns True on success."""
    client = OscClient()
    try:
        tempo = client.get_tempo()
        if tempo is not None:
            print(f"AbletonOSC connected — tempo: {tempo:.1f} BPM")
            return True
        print("ERROR: connected but no tempo reply.")
        return False
    except TimeoutError as e:
        print(f"ERROR: {e}")
        return False
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AbletonOSC connectivity check")
    parser.add_argument("--check", action="store_true", help="Test connection")
    args = parser.parse_args()
    if args.check:
        check_connection()
