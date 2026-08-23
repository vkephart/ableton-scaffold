from typing import Tuple, Any, Callable
from .handler import AbletonOSCHandler

class ReturnTrackHandler(AbletonOSCHandler):
    """
    Read-only access to return tracks.

    Stock AbletonOSC cannot see return tracks at all. song.py exposes only
    create_return_track and delete_return_track, and return tracks do not appear
    in song.tracks, so /live/song/get/track_names and every track-scoped handler
    skip them entirely, leaving a session's return tracks undocumentable.

    Everything here is a getter. Nothing in this module can modify the set.
    """

    def __init__(self, manager):
        super().__init__(manager)
        self.class_identifier = "return"

    def init_api(self):
        def create_return_callback(func: Callable, *args):
            """
            Wraps a callback that expects (return_index, *rest) and resolves the
            Return track before calling func. Mirrors create_track_callback in
            track.py, including echoing the index back at the head of the reply.
            """
            def return_callback(params: Tuple[Any]):
                return_index = int(params[0])
                returns = self.song.return_tracks
                if return_index < 0 or return_index >= len(returns):
                    self.logger.warning("Return index %d out of range (%d returns)" %
                                        (return_index, len(returns)))
                    return (return_index,)
                rv = func(returns[return_index], *args, tuple(params[1:]))
                if rv is not None:
                    return (return_index, *rv)
            return return_callback

        def return_get_num_returns(params: Tuple[Any] = ()) -> Tuple:
            return (len(self.song.return_tracks),)

        def return_get_names(params: Tuple[Any] = ()) -> Tuple:
            return tuple(rt.name for rt in self.song.return_tracks)

        def return_get_device_names(return_track, params: Tuple[Any] = ()) -> Tuple:
            return tuple(device.name for device in return_track.devices)

        def return_get_device_class_names(return_track, params: Tuple[Any] = ()) -> Tuple:
            return tuple(device.class_name for device in return_track.devices)

        def return_get_num_devices(return_track, params: Tuple[Any] = ()) -> Tuple:
            return (len(return_track.devices),)

        def return_get_mixer(return_track, params: Tuple[Any] = ()) -> Tuple:
            mixer = return_track.mixer_device
            return (mixer.volume.value, mixer.panning.value, int(return_track.mute))

        def return_get_device_parameter_names(return_track, params: Tuple[Any] = ()) -> Tuple:
            device_index = int(params[0])
            if device_index < 0 or device_index >= len(return_track.devices):
                return ()
            device = return_track.devices[device_index]
            return (device_index, *[p.name for p in device.parameters])

        def return_get_device_parameter_values(return_track, params: Tuple[Any] = ()) -> Tuple:
            device_index = int(params[0])
            if device_index < 0 or device_index >= len(return_track.devices):
                return ()
            device = return_track.devices[device_index]
            return (device_index, *[p.value for p in device.parameters])

        def return_get_device_parameter_value_string(return_track, params: Tuple[Any] = ()) -> Tuple:
            #--------------------------------------------------------------------------------
            # str_for_value gives the plugin's own display string, which is the only
            # trustworthy source of real UI units. Raw values use per-parameter scales.
            #--------------------------------------------------------------------------------
            device_index, param_index = int(params[0]), int(params[1])
            if device_index < 0 or device_index >= len(return_track.devices):
                return ()
            device = return_track.devices[device_index]
            if param_index < 0 or param_index >= len(device.parameters):
                return ()
            param = device.parameters[param_index]
            return (device_index, param_index, param.str_for_value(param.value))

        self.osc_server.add_handler("/live/return/get/num_returns", return_get_num_returns)
        self.osc_server.add_handler("/live/return/get/names", return_get_names)
        self.osc_server.add_handler("/live/return/get/num_devices",
                                    create_return_callback(return_get_num_devices))
        self.osc_server.add_handler("/live/return/get/devices/name",
                                    create_return_callback(return_get_device_names))
        self.osc_server.add_handler("/live/return/get/devices/class_name",
                                    create_return_callback(return_get_device_class_names))
        self.osc_server.add_handler("/live/return/get/mixer",
                                    create_return_callback(return_get_mixer))
        self.osc_server.add_handler("/live/return/get/device/parameters/name",
                                    create_return_callback(return_get_device_parameter_names))
        self.osc_server.add_handler("/live/return/get/device/parameters/value",
                                    create_return_callback(return_get_device_parameter_values))
        self.osc_server.add_handler("/live/return/get/device/parameter/value_string",
                                    create_return_callback(return_get_device_parameter_value_string))
