from typing import Tuple, Any, Callable, Optional
from .handler import AbletonOSCHandler
import Live

class ArrangementClipHandler(AbletonOSCHandler):
    """
    Note-level access to clips in the Arrangement view.

    Stock AbletonOSC exposes arrangement clip metadata (name, length, start_time)
    via the /live/track/get/arrangement_clips/* handlers, but note access is
    limited to Session clip slots. These handlers close that gap.

    Arrangement clips have no slot index, so they are addressed by their
    start_time on the timeline, matched within a small tolerance to absorb
    float rounding in transit over OSC.
    """

    #--------------------------------------------------------------------------------
    # Tolerance in beats when matching a clip by its start_time. Clip starts land on
    # meaningful subdivisions, so anything under a 1/256th note is float noise.
    #--------------------------------------------------------------------------------
    START_TIME_TOLERANCE = 0.001

    def __init__(self, manager):
        super().__init__(manager)
        self.class_identifier = "arrangement_clip"

    def init_api(self):
        #--------------------------------------------------------------------------------
        # Clip automation envelopes on Session clips. Lives in this module rather than a
        # new handler class because adding a class needs an Ableton restart; a module
        # reload picks these up. Live's API: clip.automation_envelope(parameter) returns
        # the envelope or None, clip.create_automation_envelope(parameter) makes one,
        # envelope.insert_step(time, length, value) writes a flat segment. A ramp is
        # many short steps, which the client supplies as (time, value) pairs.
        #--------------------------------------------------------------------------------
        def _session_clip(track_index, slot_index):
            slot = self.song.tracks[track_index].clip_slots[slot_index]
            return slot.clip if slot.has_clip else None

        def _write_envelope(clip, parameter, points):
            #--------------------------------------------------------------------------------
            # points: flat (time, value, time, value, ...). Each value holds from its time
            # until the next time; the last holds to the end of the clip.
            #--------------------------------------------------------------------------------
            clip.clear_envelope(parameter)
            env = clip.automation_envelope(parameter)
            if env is None:
                env = clip.create_automation_envelope(parameter)
            times = [float(points[i]) for i in range(0, len(points), 2)]
            values = [float(points[i]) for i in range(1, len(points), 2)]
            n = min(len(times), len(values))
            for i in range(n):
                end = times[i + 1] if i + 1 < n else clip.length
                length = end - times[i]
                if length > 0:
                    env.insert_step(times[i], length, values[i])
            return n

        def clip_set_envelope_send(params):
            track_index, slot_index, send_index = int(params[0]), int(params[1]), int(params[2])
            clip = _session_clip(track_index, slot_index)
            if clip is None:
                return (track_index, slot_index, send_index, 0)
            parameter = self.song.tracks[track_index].mixer_device.sends[send_index]
            n = _write_envelope(clip, parameter, params[3:])
            return (track_index, slot_index, send_index, n)

        def clip_set_envelope_param(params):
            track_index, slot_index = int(params[0]), int(params[1])
            device_index, param_index = int(params[2]), int(params[3])
            clip = _session_clip(track_index, slot_index)
            if clip is None:
                return (track_index, slot_index, device_index, param_index, 0)
            parameter = self.song.tracks[track_index].devices[device_index].parameters[param_index]
            n = _write_envelope(clip, parameter, params[4:])
            return (track_index, slot_index, device_index, param_index, n)

        def clip_clear_envelope_send(params):
            track_index, slot_index, send_index = int(params[0]), int(params[1]), int(params[2])
            clip = _session_clip(track_index, slot_index)
            if clip is not None:
                clip.clear_envelope(self.song.tracks[track_index].mixer_device.sends[send_index])
            return (track_index, slot_index, send_index)

        self.osc_server.add_handler("/live/clip/set/envelope/send", clip_set_envelope_send)
        self.osc_server.add_handler("/live/clip/set/envelope/param", clip_set_envelope_param)
        self.osc_server.add_handler("/live/clip/clear/envelope/send", clip_clear_envelope_send)

        def find_clip_by_start_time(track_index: int, clip_start_time: float):
            track = self.song.tracks[track_index]
            for clip in track.arrangement_clips:
                if abs(clip.start_time - clip_start_time) < self.START_TIME_TOLERANCE:
                    return clip
            return None

        def arrangement_clip_get_clips(params: Tuple[Any]) -> Tuple:
            """
            Interleaved (start_time, length) for every arrangement clip on a track.

            Stock AbletonOSC splits this across /live/track/get/arrangement_clips/start_time
            and /length, which costs two round trips per track and, more importantly,
            raises on Group tracks: Live rejects .arrangement_clips on Master, Group and
            Return tracks, the stock handler does not guard it, and the exception means
            no reply is ever sent, so the client hangs until its timeout. Bus-heavy
            sessions hit this on every group track.
            """
            track_index = int(params[0])
            track = self.song.tracks[track_index]

            try:
                clips = list(track.arrangement_clips)
            except RuntimeError:
                #--------------------------------------------------------------------------------
                # Group track (or any other track type Live refuses). Not an error condition:
                # such tracks legitimately hold no arrangement clips. Reply with an empty set
                # so the client moves on immediately instead of stalling on a timeout.
                #--------------------------------------------------------------------------------
                self.logger.info("Track %d has no arrangement clips (group/return/master)" % track_index)
                return (track_index,)

            values = []
            for clip in clips:
                values += [clip.start_time, clip.length]
            return (track_index, *values)

        def arrangement_clip_get_notes(params: Tuple[Any]) -> Tuple:
            #--------------------------------------------------------------------------------
            # Cast defensively: clients such as TouchOSC send all numerics as float.
            #--------------------------------------------------------------------------------
            track_index = int(params[0])
            clip_start_time = float(params[1])

            clip = find_clip_by_start_time(track_index, clip_start_time)
            if clip is None:
                self.logger.warning("No arrangement clip on track %d at start_time %f" %
                                    (track_index, clip_start_time))
                return (track_index, clip_start_time)
            if not clip.is_midi_clip:
                self.logger.warning("Arrangement clip on track %d at start_time %f is not a MIDI clip" %
                                    (track_index, clip_start_time))
                return (track_index, clip_start_time)

            #--------------------------------------------------------------------------------
            # Signature is get_notes_extended(from_pitch, pitch_span, from_time, time_span).
            # Times are relative to the clip's own start, not the arrangement timeline.
            #--------------------------------------------------------------------------------
            notes = clip.get_notes_extended(0, 128, 0, clip.length)

            all_note_attributes = []
            for note in notes:
                all_note_attributes += [note.pitch, note.start_time,
                                        note.duration, note.velocity, note.mute]
            return (track_index, clip_start_time, *all_note_attributes)

        def arrangement_clip_set_notes(params: Tuple[Any]) -> Tuple:
            track_index = int(params[0])
            clip_start_time = float(params[1])
            note_data = params[2:]

            if len(note_data) % 5 != 0:
                raise ValueError("Note data must be a multiple of 5 values "
                                 "(pitch, start_time, duration, velocity, mute)")

            clip = find_clip_by_start_time(track_index, clip_start_time)
            if clip is None:
                self.logger.warning("No arrangement clip on track %d at start_time %f" %
                                    (track_index, clip_start_time))
                return (track_index, clip_start_time, 0)
            if not clip.is_midi_clip:
                self.logger.warning("Arrangement clip on track %d at start_time %f is not a MIDI clip" %
                                    (track_index, clip_start_time))
                return (track_index, clip_start_time, 0)

            notes = []
            for offset in range(0, len(note_data), 5):
                pitch, start_time, duration, velocity, mute = note_data[offset:offset + 5]
                note = Live.Clip.MidiNoteSpecification(pitch=int(pitch),
                                                       start_time=float(start_time),
                                                       duration=float(duration),
                                                       velocity=int(velocity),
                                                       mute=bool(mute))
                notes.append(note)

            #--------------------------------------------------------------------------------
            # Replace rather than merge: clear the clip's full pitch and time range first,
            # so a set is idempotent and does not stack duplicate notes on repeat pushes.
            #--------------------------------------------------------------------------------
            clip.remove_notes_extended(0, 128, 0, clip.length)
            if notes:
                clip.add_new_notes(tuple(notes))

            return (track_index, clip_start_time, len(notes))

        self.osc_server.add_handler("/live/arrangement_clip/get/clips", arrangement_clip_get_clips)
        self.osc_server.add_handler("/live/arrangement_clip/get/notes", arrangement_clip_get_notes)
        self.osc_server.add_handler("/live/arrangement_clip/set/notes", arrangement_clip_set_notes)
