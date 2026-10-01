import config as cfg
import json
from pathlib import Path

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, url_for, send_from_directory,
)
from werkzeug.utils import secure_filename

from .. import db
from ..models import Job, Hotfolder
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
    except FileNotFoundError:
        flash("Job saved, but the hot folder path for this unit does not exist yet. "
              "Set it on the Settings page and use Re-send.", "warning")
    except Exception:
        current_app.logger.exception("Hot folder submission failed")
        flash("Job saved, but writing to the hot folder failed. Use Re-send once fixed.", "warning")

    flash("Job submitted to hot folder.", "success")
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


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    default_paths = dict(cfg.HOTFOLDERS)
    if request.method == "POST":
        for unit in default_paths:
            path = request.form.get(f"path_{unit}", "").strip()
            if path != "":
                row = Hotfolder.query.get(unit) or Hotfolder(unit=unit, path=path)
                if not row.path:
                    row.path = path
                row.path = path
                db.session.add(row)
        db.session.commit()
        flash("Hot folder paths saved.", "success")
        return redirect(url_for("main.settings"))
    current = unit_folders()
    return render_template("settings.html", folders=current)


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
