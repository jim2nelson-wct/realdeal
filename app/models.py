import uuid
from datetime import datetime

import config
from . import db


def _new_id():
    return uuid.uuid4().hex


class Job(db.Model):
    __tablename__ = "jobs"

    # status lifecycle: pending -> confirmed | unknown | failed
    status = db.Column(db.String(20), nullable=False, default="pending")
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.id is None:
            self.id = _new_id()

    id = db.Column(db.String(32), primary_key=True, default=_new_id)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    unit = db.Column(db.String(1), nullable=False, default="1")
    copies = db.Column(db.Integer, nullable=False, default=1)
    pageno = db.Column(db.Integer, default=0)
    rotate = db.Column(db.Integer, default=0)
    scale = db.Column(db.Integer, default=100)
    mirror = db.Column(db.Boolean, default=False)
    imgconf = db.Column(db.String(200), default="")
    notes = db.Column(db.String(500), default="")
    delete_after_rip = db.Column(db.Boolean, default=False)
    delete_after_print = db.Column(db.Boolean, default=False)

    source_filename = db.Column(db.String(300), nullable=False)
    source_ext = db.Column(db.String(20), nullable=False)
    thumb_filename = db.Column(db.String(300), default="")

    # cut outline: None = no cut
    cut_bleed = db.Column(db.Float, default=None)
    cut_radius = db.Column(db.Float, default=0.0)


class Layout(db.Model):
    __tablename__ = "layouts"

    id = db.Column(db.String(32), primary_key=True, default=_new_id)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    name = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.String(200), default="")
    unit = db.Column(db.String(1), nullable=False, default="1")
    copies = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="pending")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.id is None:
            self.id = _new_id()


class LayoutItem(db.Model):
    __tablename__ = "layout_items"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    layout_id = db.Column(db.String(32), db.ForeignKey("layouts.id"), nullable=False)
    job_id = db.Column(db.String(32), db.ForeignKey("jobs.id"), nullable=False)
    xposition = db.Column(db.Float, nullable=False, default=0.0)
    yposition = db.Column(db.Float, nullable=False, default=0.0)
    rotate = db.Column(db.Integer, default=0)

    job = db.relationship("Job")


class Hotfolder(db.Model):
    __tablename__ = "hotfolders"

    unit = db.Column(db.String(1), primary_key=True)
    path = db.Column(db.String(500), nullable=False)


class LogSettings(db.Model):
    __tablename__ = "log_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    hotxml_log_path = db.Column(db.String(500), nullable=False, default="")

    @classmethod
    def value_or_default(cls):
        row = cls.query.get(1)
        if row and row.hotxml_log_path:
            return row.hotxml_log_path
        return config.HOTXML_LOG
