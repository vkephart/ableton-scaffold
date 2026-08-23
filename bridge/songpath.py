"""
songpath.py — resolve where song folders live.

The bridge scripts used to compute `<repo>/songs/<name>/` from their own location,
which only holds while the songs sit inside the same checkout as the scripts. Once
the scaffolding and a track repo are separate checkouts that assumption breaks, so
the songs root is now explicit.

Resolution order, first hit wins:

  1. --songs-dir on the command line
  2. $ABLETON_SONGS_DIR
  3. ./songs under the current working directory
  4. <bridge-repo>/songs — the old behaviour, kept so an existing single-repo
     checkout keeps working unchanged

Only 1 and 2 name a root that must exist; 3 and 4 are probed and skipped if absent.
That way an explicit setting that points nowhere fails loudly instead of quietly
falling through to some other folder.
"""

import os

ENV_VAR = "ABLETON_SONGS_DIR"

# The repo holding these scripts, one level up from bridge/.
BRIDGE_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def add_songs_dir_arg(parser):
    """Register --songs-dir on an ArgumentParser. Same flag on every script."""
    parser.add_argument(
        "--songs-dir",
        default=None,
        help=("Directory holding the song folders. Defaults to $%s, then ./songs, "
              "then <bridge-repo>/songs." % ENV_VAR),
    )


def resolve_songs_dir(songs_dir=None):
    """Return the absolute songs root, or raise SongPathError explaining what was tried."""
    if songs_dir:
        path = os.path.abspath(os.path.expanduser(songs_dir))
        if not os.path.isdir(path):
            raise SongPathError("--songs-dir %s does not exist." % path)
        return path

    from_env = os.environ.get(ENV_VAR)
    if from_env:
        path = os.path.abspath(os.path.expanduser(from_env))
        if not os.path.isdir(path):
            raise SongPathError("$%s is set to %s, which does not exist." % (ENV_VAR, path))
        return path

    for candidate in (os.path.join(os.getcwd(), "songs"),
                      os.path.join(BRIDGE_REPO, "songs")):
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)

    probed = []
    for candidate in (os.path.join(os.getcwd(), "songs"),
                      os.path.join(BRIDGE_REPO, "songs")):
        if candidate not in probed:
            probed.append(candidate)

    raise SongPathError(
        "Cannot find a songs directory.\n"
        "  Tried: $%s (unset), %s\n"
        "  Pass --songs-dir /path/to/track-repo, or export %s."
        % (ENV_VAR, ", ".join(probed), ENV_VAR)
    )


def resolve_song_dir(song, songs_dir=None):
    """Return the absolute folder for one song, or raise SongPathError."""
    root = resolve_songs_dir(songs_dir)
    path = os.path.join(root, song)
    if not os.path.isdir(path):
        existing = sorted(name for name in os.listdir(root)
                          if os.path.isdir(os.path.join(root, name)))
        listing = ", ".join(existing) if existing else "(none)"
        raise SongPathError(
            "No song folder '%s' in %s.\n  Songs found there: %s" % (song, root, listing)
        )
    return path


def display_path(path):
    """Path for printing: relative to the working directory when that is shorter."""
    try:
        relative = os.path.relpath(path, os.getcwd())
    except ValueError:      # different drive on Windows
        return path
    return relative if len(relative) < len(path) else path


class SongPathError(Exception):
    """Raised when the songs root or a song folder cannot be resolved."""
