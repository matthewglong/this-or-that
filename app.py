#!/usr/bin/env python3
import os
import random
import shutil
import uuid
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash

from sources.registry import autoload, get as get_source, list_sources

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(24))

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIR / "uploads"

# Load/auto-discover all sources in sources/ package
autoload()

# In-memory game store keyed by game_id
GAMES: Dict[str, dict] = {}

def ensure_game() -> str:
    gid = session.get("game_id")
    if gid and gid in GAMES:
        return gid
    gid = uuid.uuid4().hex[:12]
    session["game_id"] = gid
    GAMES[gid] = {
        "channels": [],            # list of dicts: {"name": str, "dir": Optional[str], "images": [str], "source": str}
        "wins": {},                # channel name -> int
        "served": {},              # channel name -> set of image identifiers (str)
        "rounds_total": 15,
        "round_index": 0,
        "current_round": None,     # tuple: ((chanA_name, img_identifier), (chanB_name, img_identifier))
    }
    return gid

def reset_game_state(gid: str, preserve_cache: bool = False):
    game = GAMES[gid]
    game["wins"] = {c["name"]: 0 for c in game["channels"]}
    game["round_index"] = 0
    game["current_round"] = None
    if not preserve_cache:
        game["served"] = {c["name"]: set() for c in game["channels"]}
    else:
        for c in game["channels"]:
            game["served"].setdefault(c["name"], set())

def pick_two_distinct_channels(channels: List[dict]) -> Tuple[dict, dict]:
    if len(channels) < 2:
        raise ValueError("Need at least two channels")
    a, b = random.sample(channels, 2)
    return a, b

def pick_unserved_image(game: dict, channel: dict) -> str:
    name = channel["name"]
    available = set(channel["images"])
    served = game["served"].setdefault(name, set())

    if len(available - served) == 0:
        served.clear()

    unseen = list(available - served)
    choice = random.choice(unseen) if unseen else random.choice(channel["images"])
    served.add(choice)
    return choice

def find_channel(game: dict, name: str) -> Optional[dict]:
    for c in game["channels"]:
        if c["name"] == name:
            return c
    return None

@app.route("/", methods=["GET"])
def index():
    ensure_game()
    srcs = [{"key": cls.key, "label": cls.label, "fields": cls.form_fields()} for cls in list_sources()]
    return render_template("index.html", sources=srcs)

@app.route("/setup", methods=["POST"])
def setup():
    gid = ensure_game()
    game = GAMES[gid]

    # Fresh uploads dir for this gid
    user_upload_dir = UPLOAD_ROOT / gid
    if user_upload_dir.exists():
        shutil.rmtree(user_upload_dir)
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    # Rounds
    try:
        rounds_total = int(request.form.get("rounds", "15"))
        rounds_total = max(5, min(100, rounds_total))
    except ValueError:
        rounds_total = 15

    # Slot indices from hidden field
    slot_indices = (request.form.get("slot_indices") or "").strip()
    if not slot_indices:
        flash("Please add at least two channels.", "error")
        return redirect(url_for("index"))

    indices = [s for s in slot_indices.split(",") if s.strip() != ""]

    channels: List[dict] = []
    for i_str in indices:
        try:
            i = int(i_str)
        except ValueError:
            continue

        source_key = (request.form.get(f"channel{i}_source") or "upload").lower()
        try:
            SourceCls = get_source(source_key)
            src = SourceCls()
        except KeyError:
            continue

        ch = src.build_channel(gid=gid, idx=i, form=request.form, files=request.files)
        if ch and ch.get("images"):
            channels.append(ch)

    if len(channels) < 2:
        flash("Please configure at least two channels with valid inputs.", "error")
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

    if game["current_round"] is None:
        chanA, chanB = pick_two_distinct_channels(game["channels"])
        imgA = pick_unserved_image(game, chanA)
        imgB = pick_unserved_image(game, chanB)
        game["current_round"] = ((chanA["name"], imgA), (chanB["name"], imgB))

    (chanA_name, imgA_id), (chanB_name, imgB_id) = game["current_round"]
    # Resolve URLs: if http(s), use as-is; else serve from uploads
    left_url = imgA_id
    right_url = imgB_id

    if not (str(imgA_id).startswith("http://") or str(imgA_id).startswith("https://")):
        chanA = find_channel(game, chanA_name)
        if chanA and chanA.get("dir"):
            left_url = url_for("serve_image", game_id=gid, channel=chanA_name, relpath=imgA_id)

    if not (str(imgB_id).startswith("http://") or str(imgB_id).startswith("https://")):
        chanB = find_channel(game, chanB_name)
        if chanB and chanB.get("dir"):
            right_url = url_for("serve_image", game_id=gid, channel=chanB_name, relpath=imgB_id)

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
        return redirect(url_for("play"))

    game["wins"][picked] = game["wins"].get(picked, 0) + 1
    game["round_index"] += 1
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

    total_rounds = max(1, game["rounds_total"])
    results = []
    for c in game["channels"]:
        name = c["name"]
        wins = int(game["wins"].get(name, 0))
        pct = round(100.0 * wins / total_rounds, 1)
        results.append({"channel": name, "wins": wins, "percent": pct})

    results.sort(key=lambda x: (-x["percent"], x["channel"].lower()))
    return render_template("results.html", results=results, rounds=total_rounds)

@app.route("/replay", methods=["POST"])
def replay():
    gid = ensure_game()
    reset_game_state(gid, preserve_cache=True)
    return redirect(url_for("play"))

@app.route("/startover", methods=["POST"])
def startover():
    gid = ensure_game()
    user_upload_dir = UPLOAD_ROOT / gid
    if user_upload_dir.exists():
        shutil.rmtree(user_upload_dir)
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
    base = (UPLOAD_ROOT / game_id / channel).resolve()
    requested = (base / relpath).resolve()
    if base in requested.parents or requested == base:
        return send_from_directory(str(base), str(Path(relpath)))
    return ("Not Found", 404)

@app.context_processor
def inject_globals():
    return {"app_title": "This or that"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
