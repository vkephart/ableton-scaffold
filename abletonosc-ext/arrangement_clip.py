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

        #--------------------------------------------------------------------------------
        # Locators (cue points). Stock AbletonOSC can read and jump to them but not make
        # or name them, and Live's API has no "add a cue at this time": set_or_delete_cue()
        # toggles a cue at the current song time. Setting current_song_time does not take
        # effect inside the same call (tested 2026-10-04: a cue toggled straight after the
        # setter landed at the old playhead), so the client moves the playhead first with
        # the stock /live/song/set/current_song_time, waits, and then calls these. Each
        # refuses unless the transport is stopped and the playhead already sits on the
        # requested time. A cue already at the time is renamed, never toggled off, so
        # repeating an add is safe. Addressed by time in beats, matched within the clip
        # tolerance; Live's cue index shifts whenever a cue is added before another.
        #--------------------------------------------------------------------------------
        def _cue_at(time):
            for cue in self.song.cue_points:
                if abs(cue.time - time) < self.START_TIME_TOLERANCE:
                    return cue
            return None

        def _playhead_refusal(time):
            if self.song.is_playing:
                return "refused: transport is playing"
            if abs(self.song.current_song_time - time) >= self.START_TIME_TOLERANCE:
                return "refused: playhead is at %s, move it to %s first" % (self.song.current_song_time, time)
            return None

        def cue_point_add(params):
            time, name = float(params[0]), str(params[1])
            cue = _cue_at(time)
            if cue is not None:
                return (time, name, "exists; " + _try_name(cue, name))
            refusal = _playhead_refusal(time)
            if refusal:
                return (time, name, refusal)
            self.song.set_or_delete_cue()
            cue = _cue_at(time)
            if cue is None:
                return (time, name, "toggled; check the cue list")
            return (time, name, "created; " + _try_name(cue, name))

        def _try_name(cue, name):
            #--------------------------------------------------------------------------------
            # CuePoint.name is read-only in Live 11.3 (AttributeError "can't set attribute",
            # 2026-10-04). Kept as a try so a Live version that allows it just works.
            #--------------------------------------------------------------------------------
            try:
                cue.name = name
                return "named"
            except AttributeError:
                return "name is read-only in this Live, rename by hand"

        def cue_point_set_name(params):
            time, name = float(params[0]), str(params[1])
            cue = _cue_at(time)
            if cue is None:
                return (time, name, "none at that time")
            return (time, name, _try_name(cue, name))

        def cue_point_delete(params):
            time = float(params[0])
            if _cue_at(time) is None:
                return (time, "none at that time")
            refusal = _playhead_refusal(time)
            if refusal:
                return (time, refusal)
            self.song.set_or_delete_cue()
            return (time, "toggled off")

        self.osc_server.add_handler("/live/song/cue_point/add", cue_point_add)
        self.osc_server.add_handler("/live/song/cue_point/set/name", cue_point_set_name)
        self.osc_server.add_handler("/live/song/cue_point/delete", cue_point_delete)

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

        #--------------------------------------------------------------------------------
        # Arrangement layout (2026-10-04). Live's Track.duplicate_clip_to_arrangement(clip,
        # time) copies a Session or Arrangement clip onto the timeline, and
        # Track.delete_clip(clip) removes one. Both are wrapped here, Arrangement clips
        # addressed by start time like the note handlers. Each says "unsupported" instead
        # of raising when this Live lacks the method, so a client can check first.
        #--------------------------------------------------------------------------------
        def arrangement_layout_capabilities(params):
            track = self.song.tracks[0]
            return (bool(hasattr(track, "duplicate_clip_to_arrangement")), bool(hasattr(track, "delete_clip")))

        def arrangement_clip_get_info(params):
            #--------------------------------------------------------------------------------
            # (start_time, end_time, name) per clip. end_time, not length: a looped clip's
            # length is its loop, while end_time is where it stops on the timeline.
            #--------------------------------------------------------------------------------
            track_index = int(params[0])
            try:
                clips = list(self.song.tracks[track_index].arrangement_clips)
            except Exception:
                clips = []
            out = [track_index]
            for clip in clips:
                out += [clip.start_time, clip.end_time, clip.name]
            return tuple(out)

        def _duplicate(track, clip, dest):
            if not hasattr(track, "duplicate_clip_to_arrangement"):
                return ("unsupported", -1.0, -1.0)
            new = track.duplicate_clip_to_arrangement(clip, dest)
            if new is None:
                return ("ok", -1.0, -1.0)
            return ("ok", new.start_time, new.end_time)

        def arrangement_clip_duplicate(params):
            track_index, src_start, dest = int(params[0]), float(params[1]), float(params[2])
            clip = find_clip_by_start_time(track_index, src_start)
            if clip is None:
                return (track_index, src_start, dest, "no clip at that start", -1.0, -1.0)
            return (track_index, src_start, dest) + _duplicate(self.song.tracks[track_index], clip, dest)

        def clip_slot_duplicate_to_arrangement(params):
            track_index, slot_index, dest = int(params[0]), int(params[1]), float(params[2])
            slot = self.song.tracks[track_index].clip_slots[slot_index]
            if not slot.has_clip:
                return (track_index, slot_index, dest, "empty slot", -1.0, -1.0)
            return (track_index, slot_index, dest) + _duplicate(self.song.tracks[track_index], slot.clip, dest)

        def arrangement_clip_delete(params):
            track_index, start = int(params[0]), float(params[1])
            track = self.song.tracks[track_index]
            clip = find_clip_by_start_time(track_index, start)
            if clip is None:
                return (track_index, start, "no clip at that start")
            if not hasattr(track, "delete_clip"):
                return (track_index, start, "unsupported")
            track.delete_clip(clip)
            return (track_index, start, "deleted")

        self.osc_server.add_handler("/live/arrangement_clip/get/capabilities", arrangement_layout_capabilities)
        self.osc_server.add_handler("/live/arrangement_clip/get/info", arrangement_clip_get_info)
        self.osc_server.add_handler("/live/arrangement_clip/duplicate", arrangement_clip_duplicate)
        self.osc_server.add_handler("/live/clip_slot/duplicate_to_arrangement", clip_slot_duplicate_to_arrangement)
        self.osc_server.add_handler("/live/arrangement_clip/delete", arrangement_clip_delete)

        def arrangement_clip_set_name(params):
            track_index, start, name = int(params[0]), float(params[1]), str(params[2])
            clip = find_clip_by_start_time(track_index, start)
            if clip is None:
                return (track_index, start, name, "no clip at that start")
            clip.name = name
            return (track_index, start, clip.name, "named")

        self.osc_server.add_handler("/live/arrangement_clip/set/name", arrangement_clip_set_name)

        #--------------------------------------------------------------------------------
        # Reversible edits (2026-10-17): mute a whole clip, or mute the notes in a pitch
        # and time window, instead of deleting anything. Muted clips and notes show greyed
        # in Live and come back with the 0 key, or with the same call and 0.
        # Note windows are in clip time, which differs from song time minus start_time
        # whenever the clip's start marker is not 0 (a clip split or trimmed by hand), so
        # get/props first and convert: clip time = song beat - start_time + start_marker.
        #--------------------------------------------------------------------------------
        def arrangement_clip_get_props(params):
            track_index, start = int(params[0]), float(params[1])
            clip = find_clip_by_start_time(track_index, start)
            if clip is None:
                return (track_index, start, "no clip at that start")
            return (track_index, start, clip.start_marker, clip.end_marker, clip.loop_start,
                    clip.loop_end, bool(clip.looping), clip.length, bool(clip.muted),
                    bool(clip.is_midi_clip))

        def arrangement_clip_set_muted(params):
            track_index, start, muted = int(params[0]), float(params[1]), bool(int(params[2]))
            clip = find_clip_by_start_time(track_index, start)
            if clip is None:
                return (track_index, start, "no clip at that start")
            clip.muted = muted
            return (track_index, start, bool(clip.muted))

        def arrangement_clip_set_notes_muted(params):
            track_index, start = int(params[0]), float(params[1])
            from_pitch, pitch_span = int(params[2]), int(params[3])
            from_time, time_span, muted = float(params[4]), float(params[5]), bool(int(params[6]))
            clip = find_clip_by_start_time(track_index, start)
            if clip is None or not clip.is_midi_clip:
                return (track_index, start, "no MIDI clip at that start")
            notes = clip.get_notes_extended(from_pitch, pitch_span, from_time, time_span)
            for note in notes:
                note.mute = muted
            clip.apply_note_modifications(notes)
            return (track_index, start, len(notes), muted)

        def arrangement_clip_add_notes(params):
            #--------------------------------------------------------------------------------
            # Adds without clearing, unlike set/notes, so a clip too large to read back in one
            # OSC reply can still take a note. Undo with remove/notes on the same window.
            #--------------------------------------------------------------------------------
            track_index, start = int(params[0]), float(params[1])
            note_data = params[2:]
            if len(note_data) % 5 != 0:
                raise ValueError("Note data must be a multiple of 5 values")
            clip = find_clip_by_start_time(track_index, start)
            if clip is None or not clip.is_midi_clip:
                return (track_index, start, "no MIDI clip at that start")
            notes = []
            for offset in range(0, len(note_data), 5):
                pitch, start_time, duration, velocity, mute = note_data[offset:offset + 5]
                notes.append(Live.Clip.MidiNoteSpecification(pitch=int(pitch), start_time=float(start_time),
                                                             duration=float(duration), velocity=int(velocity),
                                                             mute=bool(mute)))
            clip.add_new_notes(tuple(notes))
            return (track_index, start, len(notes))

        def arrangement_clip_remove_notes(params):
            track_index, start = int(params[0]), float(params[1])
            from_pitch, pitch_span = int(params[2]), int(params[3])
            from_time, time_span = float(params[4]), float(params[5])
            clip = find_clip_by_start_time(track_index, start)
            if clip is None or not clip.is_midi_clip:
                return (track_index, start, "no MIDI clip at that start")
            count = len(clip.get_notes_extended(from_pitch, pitch_span, from_time, time_span))
            clip.remove_notes_extended(from_pitch, pitch_span, from_time, time_span)
            return (track_index, start, count)

        self.osc_server.add_handler("/live/arrangement_clip/add/notes", arrangement_clip_add_notes)
        self.osc_server.add_handler("/live/arrangement_clip/remove/notes", arrangement_clip_remove_notes)
        self.osc_server.add_handler("/live/arrangement_clip/get/props", arrangement_clip_get_props)
        self.osc_server.add_handler("/live/arrangement_clip/set/muted", arrangement_clip_set_muted)
        self.osc_server.add_handler("/live/arrangement_clip/set/notes_muted", arrangement_clip_set_notes_muted)
