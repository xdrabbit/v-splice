from flask import Flask, render_template, request, jsonify, send_from_directory
import os, threading, uuid, json
from vr_vary import process_folder

# ── Job state storage ─────────────────────────────────────────────────────────
jobs = {}          # job_id -> dict
jobs_lock = threading.Lock()

def set_job(job_id, **kwargs):
    with jobs_lock:
        jobs.setdefault(job_id, {}).update(kwargs)

def windows_to_wsl_path(path):
    if path.startswith('/'):
        return path
    drive_letter = path[0].lower()
    return f'/mnt/{drive_letter}' + path[2:].replace('\\', '/')

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/process", methods=["POST"])
def process():
    data   = request.get_json()
    folder = windows_to_wsl_path(data.get("folder", ""))

    if not folder or not os.path.isdir(folder):
        return jsonify({"success": False, "message": f"Invalid folder path: {folder}"}), 400

    params = {
        "crossfade_sec":     float(data.get("crossfade",       0.25)),
        "reverse_prob":      float(data.get("reverse_prob",    0.15)),
        "min_speed":         float(data.get("min_speed",       0.3)),
        "max_speed":         float(data.get("max_speed",       5.0)),
        "zoom_min":          1.0,
        "zoom_max":          1.0 + float(data.get("zoom_intensity", 0.15)),
        "pan_range":         float(data.get("pan_amount",      0.05)),
        "effect_prob":       float(data.get("effect_prob",     0.4)),
        "pitch_shift_prob":  float(data.get("pitch_shift_prob", 0.15)),
        "wave_amplitude":    float(data.get("wave_amplitude",  0.5)),
        "stutter_prob":      float(data.get("stutter_prob",    0.17)),
    }

    job_id = str(uuid.uuid4())[:8]
    set_job(job_id, state="starting", current=0, total=0, message="Starting…", output=None)

    def progress_cb(current, total, clip_name=""):
        set_job(job_id, state="running", current=current, total=total,
                message=f"Processing clip {current}/{total}: {clip_name}")

    def run():
        try:
            ok, out_path, msg = process_folder(folder, progress_callback=progress_cb, **params)
            if ok:
                filename = os.path.basename(out_path)
                # Serve from /output/<folder_path>/<filename> by making a symlink-friendly route
                # We encode the full absolute path for the serve_output route
                set_job(job_id, state="done", message=msg,
                        output=out_path, filename=filename)
            else:
                set_job(job_id, state="error", message=msg, output=None)
        except Exception as e:
            set_job(job_id, state="error", message=str(e), output=None)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/status/<job_id>")
def status(job_id):
    with jobs_lock:
        job = jobs.get(job_id, {"state": "unknown"})
    return jsonify(job)

@app.route("/output/<path:filepath>")
def serve_output(filepath):
    """Serve any absolute path as /output/<abs_path>"""
    abs_path = '/' + filepath
    directory = os.path.dirname(abs_path)
    filename  = os.path.basename(abs_path)
    return send_from_directory(directory, filename)

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=55123, threaded=True)
