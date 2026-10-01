import config as cfg
import json
import os
from collections import deque
from pathlib import Path

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, url_for, send_from_directory,
)
from werkzeug.utils import secure_filename

from .. import db
from ..models import Job, Hotfolder, LogSettings
from ..rip.job_builder import WasatchXML
from ..rip import status as rip_status
from ..rip.status import analyze_url_or_path
from ..thumbs import make_thumb

bp = Blueprint("main", __name__)


def allowed_file(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in cfg.ALLOWED_EXTENSIONS


def unit_folders():
    rows = {h.unit: h.path for h in Hotfolder.query.all()}
    merged = dict(cfg.HOTFOLDERS)
    merged.update(rows)
    return merged


@bp.route("/")
def index():
    jobs = Job.query.order_by(Job.created_at.desc()).all()
    return render_template("index.html", jobs=jobs)


@bp.route("/new", methods=["GET", "POST"])
def new_job():
    if request.method == "GET":
        return render_template("new_job.html", units=sorted(unit_folders().keys()))

    uploaded = request.files.get("artwork")
    if not uploaded or uploaded.filename == "":
        flash("Choose an artwork file to submit.", "danger")
        return redirect(url_for("main.new_job"))

    if not allowed_file(uploaded.filename):
        flash("Unsupported file type. Allowed: " + ", ".join(sorted(cfg.ALLOWED_EXTENSIONS)), "danger")
        return redirect(url_for("main.new_job"))

    unit = request.form.get("unit", "1")
    folders = unit_folders()
    if unit not in folders:
        flash("Unknown print unit.", "danger")
        return redirect(url_for("main.new_job"))

    job = Job(
        name=request.form.get("name", "").strip() or "Untitled job",
        unit=unit,
        copies=int(request.form.get("copies", 1) or 1),
        pageno=int(request.form.get("pageno", 0) or 0),
        rotate=int(request.form.get("rotate", 0) or 0),
        scale=int(request.form.get("scale", 100) or 100),
        mirror=bool(request.form.get("mirror")),
        imgconf=request.form.get("imgconf", "").strip(),
        notes=request.form.get("notes", "").strip(),
        delete_after_rip=bool(request.form.get("delete_after_rip")),
        delete_after_print=bool(request.form.get("delete_after_print")),
    )
    job.source_filename = secure_filename(uploaded.filename)
    ext = Path(job.source_filename).suffix.lower()
    job.source_ext = ext

    job_dir = cfg.UPLOAD_DIR / job.id
    job_dir.mkdir(parents=True, exist_ok=True)
    artwork_path = job_dir / job.source_filename
    uploaded.save(artwork_path)

    thumb = None
    try:
        thumb = make_thumb(artwork_path, job_dir)
    except Exception:
        current_app.logger.exception("Thumbnail generation failed")
    job.thumb_filename = thumb.name if thumb else ""

    if job.pageno and job.pageno > 0:
        analysis = analyze_url_or_path(str(artwork_path))
        if analysis and analysis["pages"] and job.pageno > analysis["pages"]:
            flash(f"That file has only {analysis['pages']} page(s); page {job.pageno} is not valid.", "danger")
            return redirect(url_for("main.new_job"))

    db.session.add(job)
    db.session.commit()

    xml = WasatchXML(job, artwork_path)
    try:
        xml.write_atomic(folders[unit])
        # confirmation handshake: did SoftRIP pick the job into its RIP queue?
        job.status = rip_status.confirm_in_rip_queue(unit, str(artwork_path))
        db.session.commit()
        if job.status == "confirmed":
            flash("Job submitted and confirmed in SoftRIP's RIP queue.", "success")
        elif job.status == "offline":
            flash("Job submitted, but SoftRIP is unreachable so delivery is unconfirmed. Use Re-check.", "warning")
        else:
            flash("Job submitted, but it hasn't appeared in the RIP queue yet. Use Re-check.", "warning")
    except FileNotFoundError:
        job.status = "failed"
        db.session.commit()
        flash("Job saved, but the hot folder path for this unit does not exist yet. "
              "Set it on the Settings page and use Re-send.", "danger")
    except Exception:
        job.status = "failed"
        db.session.commit()
        current_app.logger.exception("Hot folder submission failed")
        flash("Job saved, but writing to the hot folder failed. Use Re-send once fixed.", "danger")
    return redirect(url_for("main.index"))


@bp.route("/api/imgconfs/<unit>")
def api_imgconfs(unit):
    confs = rip_status.get_imgconfs(unit)
    return {"online": bool(confs) or rip_status.get_system()["online"], "imgconfs": confs}


@bp.route("/api/file-analysis/<job_id>")
def api_file_analysis(job_id):
    job = Job.query.get_or_404(job_id)
    info = analyze_url_or_path(str(cfg.UPLOAD_DIR / job.id / job.source_filename))
    if info is None:
        return {"available": False}, 503
    return {"available": True, **info}


@bp.route("/status")
def rip_status_page():
    system = rip_status.get_system()
    queues = {u["number"]: rip_status.get_queue(u["number"]) for u in system["units"] if u.get("number")}
    return render_template("status.html", system=system, queues=queues)


@bp.route("/jobs/<job_id>/check", methods=["POST"])
def check(job_id):
    job = Job.query.get_or_404(job_id)
    artwork_path = cfg.UPLOAD_DIR / job.id / job.source_filename
    if not artwork_path.exists():
        flash("Artwork file is missing on disk; cannot verify.", "danger")
        return redirect(url_for("main.detail", job_id=job.id))
    result = rip_status.confirm_in_rip_queue(job.unit, str(artwork_path), attempts=4, delay=0.5)
    if result != "offline":
        job.status = result
        db.session.commit()
    msg = {
        "confirmed": "Job is confirmed in SoftRIP's RIP queue.",
        "pending": "Job was not found in the RIP queue yet.",
        "offline": "SoftRIP is unreachable; status unchanged.",
    }[result]
    flash(msg, "success" if result == "confirmed" else "warning")
    return redirect(url_for("main.detail", job_id=job.id))


@bp.route("/logs")
def logs():
    log_path = LogSettings.value_or_default()
    tail = ""
    exists = bool(log_path) and os.path.exists(log_path)
    if exists:
        try:
            lines = int(request.args.get("lines", 100))
        except ValueError:
            lines = 100
        lines = max(1, min(lines, 2000))
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            deque_tail = deque(f, maxlen=lines)
        tail = "".join(deque_tail)
    return render_template("logs.html", log_path=log_path,
                           exists=exists, tail=tail,
                           lines=request.args.get("lines", 100),
                           refresh=request.args.get("refresh", ""))


@bp.route("/api/logs")
def api_logs():
    log_path = LogSettings.value_or_default()
    if not log_path or not os.path.exists(log_path):
        return {"exists": False, "tail": ""}
    try:
        lines = int(request.args.get("lines", 100))
    except ValueError:
        lines = 100
    lines = max(1, min(lines, 2000))
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        tail = "".join(deque(f, maxlen=lines))
    return {"exists": True, "tail": tail}


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for unit in dict(cfg.HOTFOLDERS):
            path = request.form.get(f"path_{unit}", "").strip()
            if path != "":
                row = Hotfolder.query.get(unit) or Hotfolder(unit=unit, path=path)
                row.path = path
                db.session.add(row)
        log_path = request.form.get("hotxml_log", "").strip()
        row = LogSettings.query.get(1) or LogSettings(id=1, hotxml_log_path=log_path)
        row.hotxml_log_path = log_path
        db.session.add(row)
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("main.settings"))
    current = unit_folders()
    log_path = LogSettings.value_or_default()
    return render_template("settings.html", folders=current, log_path=log_path)


@bp.route("/jobs/<job_id>/resend", methods=["POST"])
def resend(job_id):
    job = Job.query.get_or_404(job_id)
    folders = unit_folders()
    artwork_path = cfg.UPLOAD_DIR / job.id / job.source_filename
    if not artwork_path.exists():
        flash("Artwork file is missing on disk; cannot re-send.", "danger")
        return redirect(url_for("main.detail", job_id=job.id))
    try:
        WasatchXML(job, artwork_path).write_atomic(folders[job.unit])
        flash("Job re-sent to hot folder.", "success")
    except Exception:
        current_app.logger.exception("Resend failed")
        flash("Re-send failed. Check the hot folder path in Settings.", "danger")
    return redirect(url_for("main.detail", job_id=job.id))


@bp.route("/jobs/<job_id>")
def detail(job_id):
    job = Job.query.get_or_404(job_id)
    xml = WasatchXML(job, cfg.UPLOAD_DIR / job.id / job.source_filename).to_xml()
    return render_template("detail.html", job=job, job_dir=cfg.UPLOAD_DIR / job.id, xml=xml)


@bp.route("/jobs/<job_id>/thumb")
def upload_thumb(job_id):
    job = Job.query.get_or_404(job_id)
    job_dir = cfg.UPLOAD_DIR / job.id
    return send_from_directory(job_dir, "thumb.png")


@bp.route("/jobs/<job_id>/delete", methods=["POST"])
def delete(job_id):
    job = Job.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    flash("Job deleted from history.", "success")
    return redirect(url_for("main.index"))
