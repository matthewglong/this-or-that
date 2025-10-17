#!/usr/bin/env python3
import os
import random
import shutil
import uuid
from pathlib import Path
from typing import Dict, List, Tuple
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}

app = Flask(__name__)
# For a local app it's fine to generate a random secret key each run.
# If you want persistent sessions across restarts, set FLASK_SECRET in env.
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(24))

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIR / "uploads"

# In-memory game store keyed by game_id
GAMES: Dict[str, dict] = {}

def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

def safe_channel_name(name: str) -> str:
    # Simple transform to clean up channel names
    clean = "".join(ch for ch in name if ch.isalnum() or ch in (" ", "_", "-", "."))
    return clean.strip() or "Channel"

def ensure_game() -> str:
    gid = session.get("game_id")
    if gid and gid in GAMES:
        return gid
    gid = uuid.uuid4().hex[:12]
    session["game_id"] = gid
    GAMES[gid] = {
        "channels": [],            # list of dicts: {"name": str, "dir": str, "images": [relpaths]}
        "wins": {},                # channel name -> int
        "served": {},              # channel name -> set of image relpaths served since last reset
        "rounds_total": 15,
        "round_index": 0,
        "current_round": None,     # tuple: ((chanA, imgA_path), (chanB, imgB_path))
    }
    return gid

def reset_game_state(gid: str, preserve_cache: bool = False):
    game = GAMES[gid]
    game["wins"] = {c["name"]: 0 for c in game["channels"]}
    game["round_index"] = 0
    game["current_round"] = None
    # Preserve served cache if requested (for Replay)
    if not preserve_cache:
        game["served"] = {c["name"]: set() for c in game["channels"]}
    else:
        # Ensure keys exist
        for c in game["channels"]:
            game["served"].setdefault(c["name"], set())

def load_images_for_channel(gid: str, channel_name: str, channel_dir: Path) -> List[str]:
    """Return sorted list of relative filepaths under channel_dir for allowed images."""
    rels = []
    for root, _, files in os.walk(channel_dir):
        for f in files:
            if allowed_file(f):
                full = Path(root) / f
                rels.append(str(full.relative_to(channel_dir)))
    rels.sort()
    return rels

def pick_two_distinct_channels(channels: List[dict]) -> Tuple[dict, dict]:
    if len(channels) < 2:
        raise ValueError("Need at least two channels")
    a, b = random.sample(channels, 2)
    return a, b

def pick_unserved_image(game: dict, channel: dict) -> str:
    """Pick an image relpath from channel that hasn't been served since last reset.
       If all served, clear the cache for that channel, then sample again.
    """
    name = channel["name"]
    available = set(channel["images"])
    served = game["served"].setdefault(name, set())

    if len(available - served) == 0:
        # Clear per requirements when channel runs out of unserved images
        served.clear()

    unseen = list(available - served)
    choice = random.choice(unseen) if unseen else random.choice(channel["images"])
    served.add(choice)
    return choice

@app.route("/", methods=["GET"])
def index():
    # Start fresh UI state, but don't wipe any uploads yet until Start Over is used
    ensure_game()
    return render_template("index.html")

@app.route("/setup", methods=["POST"])
def setup():
    gid = ensure_game()
    game = GAMES[gid]
    # Clean out any existing content for a brand new setup
    # Remove existing uploads for this gid
    user_upload_dir = UPLOAD_ROOT / gid
    if user_upload_dir.exists():
        shutil.rmtree(user_upload_dir)
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    # Extract rounds selection
    try:
        rounds_total = int(request.form.get("rounds", "15"))
        rounds_total = max(5, min(100, rounds_total))
    except ValueError:
        rounds_total = 15

    # Read how many channel slots were present
    # The page sends dynamic inputs named channel0, channel1, ... containing directory uploads
    channel_field_names = [k for k in request.files.keys() if k.startswith("channel")]
    channel_field_names.sort()

    channels: List[dict] = []
    for field in channel_field_names:
        files = request.files.getlist(field)
        if not files:
            continue

        # Infer channel name from the first file's path (webkitdirectory includes relative path).
        # Expect something like "<foldername>/sub/filename.jpg"
        first = files[0]
        relpath = first.filename or ""
        folder_name = relpath.split("/")[0].split("\\")[0] if "/" in relpath or "\\" in relpath else Path(relpath).stem
        channel_name = safe_channel_name(folder_name) or safe_channel_name(field)

        # Create channel dir
        ch_dir = user_upload_dir / channel_name
        ch_dir.mkdir(parents=True, exist_ok=True)

        saved_any = False
        for f in files:
            if not f or not f.filename:
                continue
            if not allowed_file(f.filename):
                continue
            # Preserve relative structure after the top-level
            parts = f.filename.split("/")
            parts = parts[1:] if len(parts) > 1 else [Path(f.filename).name]
            dest = ch_dir
            # recreate subdirs if present
            if len(parts) > 1:
                dest = ch_dir / Path(*parts[:-1])
                dest.mkdir(parents=True, exist_ok=True)
            dest_file = (dest / Path(parts[-1])).resolve()
            # Avoid directory traversal
            if ch_dir not in dest_file.parents and dest_file != ch_dir:
                continue
            f.save(str(dest_file))
            saved_any = True

        # Skip empty channels
        if saved_any:
            images = load_images_for_channel(gid, channel_name, ch_dir)
            if images:
                channels.append({"name": channel_name, "dir": str(ch_dir), "images": images})

    if len(channels) < 2:
        flash("Please provide at least two folders with images.", "error")
        return redirect(url_for("index"))

    # Initialize game
    game["channels"] = channels
    game["rounds_total"] = rounds_total
    game["wins"] = {c["name"]: 0 for c in channels}
    game["served"] = {c["name"]: set() for c in channels}
    game["round_index"] = 0
    game["current_round"] = None

    return redirect(url_for("play"))

@app.route("/play", methods=["GET"])
def play():
    gid = ensure_game()
    game = GAMES[gid]

    if not game["channels"]:
        return redirect(url_for("index"))

    if game["round_index"] >= game["rounds_total"]:
        return redirect(url_for("results"))

    # If there's a current round prepared (e.g., after refresh), reuse it
    if game["current_round"] is None:
        chanA, chanB = pick_two_distinct_channels(game["channels"])
        imgA = pick_unserved_image(game, chanA)
        imgB = pick_unserved_image(game, chanB)
        game["current_round"] = ((chanA["name"], imgA), (chanB["name"], imgB))

    (chanA_name, imgA_rel), (chanB_name, imgB_rel) = game["current_round"]

    # Build URLs for images
    left_url = url_for("serve_image", game_id=gid, channel=chanA_name, relpath=imgA_rel)
    right_url = url_for("serve_image", game_id=gid, channel=chanB_name, relpath=imgB_rel)

    # The UI should not reveal channel names; keep them server-side only.
    return render_template(
        "play.html",
        round_number=game["round_index"] + 1,
        rounds_total=game["rounds_total"],
        left_url=left_url,
        right_url=right_url,
    )

@app.route("/choose", methods=["POST"])
def choose():
    gid = ensure_game()
    game = GAMES[gid]
    choice = request.form.get("choice")
    if not game["current_round"]:
        return redirect(url_for("play"))

    (chanA_name, _), (chanB_name, _) = game["current_round"]

    if choice == "left":
        picked = chanA_name
    elif choice == "right":
        picked = chanB_name
    else:
        # Invalid choice; ignore and show same round
        return redirect(url_for("play"))

    # Record the win
    game["wins"][picked] = game["wins"].get(picked, 0) + 1
    game["round_index"] += 1
    # Clear current round so a new one can be generated
    game["current_round"] = None

    if game["round_index"] >= game["rounds_total"]:
        return redirect(url_for("results"))
    return redirect(url_for("play"))

@app.route("/results", methods=["GET"])
def results():
    gid = ensure_game()
    game = GAMES[gid]
    if not game["channels"]:
        return redirect(url_for("index"))

    total_rounds = max(1, game["rounds_total"])  # guard against divide-by-zero
    results = []
    for c in game["channels"]:
        name = c["name"]
        wins = int(game["wins"].get(name, 0))
        pct = round(100.0 * wins / total_rounds, 1)
        results.append({"channel": name, "wins": wins, "percent": pct})

    # Sort descending by percent
    results.sort(key=lambda x: (-x["percent"], x["channel"].lower()))

    return render_template("results.html", results=results, rounds=total_rounds)

@app.route("/replay", methods=["POST"])
def replay():
    gid = ensure_game()
    reset_game_state(gid, preserve_cache=True)
    # Keep same rounds_total
    return redirect(url_for("play"))

@app.route("/startover", methods=["POST"])
def startover():
    gid = ensure_game()
    # Remove uploads for this game and reset
    user_upload_dir = UPLOAD_ROOT / gid
    if user_upload_dir.exists():
        shutil.rmtree(user_upload_dir)
    # Reinitialize game record
    GAMES[gid] = {
        "channels": [],
        "wins": {},
        "served": {},
        "rounds_total": 15,
        "round_index": 0,
        "current_round": None,
    }
    return redirect(url_for("index"))

@app.route("/uploads/<game_id>/<channel>/<path:relpath>")
def serve_image(game_id, channel, relpath):
    # Serve image files safely
    base = (UPLOAD_ROOT / game_id / channel).resolve()
    requested = (base / relpath).resolve()
    if base in requested.parents or requested == base:
        return send_from_directory(str(base), str(Path(relpath)))
    return ("Not Found", 404)

@app.template_filter("pretty_channel")
def pretty_channel(name: str) -> str:
    # For potential future use where we might display channel names without revealing source
    return name

@app.context_processor
def inject_globals():
    return {"app_title": "This or that"}

if __name__ == "__main__":
    # For local development
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
