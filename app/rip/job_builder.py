import logging
import os
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)


class WasatchXML:
    def __init__(self, job, artwork_path: Path):
        self.job = job
        self.artwork_path = Path(artwork_path)

    def to_xml(self) -> str:
        j = self.job
        attrs = {'ACTION': 'JOB'}
        lines = ['<?xml version="1.0" encoding="utf-8"?>', _tag_open('WASATCH', attrs)]
        page_attrs = {}
        if j.rotate:
            page_attrs['XPOSITION'] = '0.0'
            page_attrs['YPOSITION'] = '0.0'
        lines.append('  ' + _tag_open('PAGE', page_attrs))
        lines.append(f'    <FileName>{_esc(str(self.artwork_path))}</FileName>')
        if j.pageno and j.pageno > 0:
            lines.append(f'    <Pageno>{j.pageno}</Pageno>')
        if j.rotate:
            lines.append(f'    <Rotate>{j.rotate}</Rotate>')
        if j.scale and j.scale != 100:
            lines.append(f'    <Scale>{j.scale}</Scale>')
        if j.mirror:
            lines.append('    <Mirror>1</Mirror>')
        if j.imgconf:
            lines.append(f'    <IMGCONF>{_esc(j.imgconf)}</IMGCONF>')
        if j.cut_bleed is not None:
            attrs = f' Bleed={j.cut_bleed}'
            if j.cut_radius:
                attrs += f' Cornerradius={j.cut_radius}'
            lines.append(f'    <Cutoutline{attrs}></Cutoutline>')
        if j.delete_after_rip:
            lines.append('    <DELETEAFTERRIP />')
        if j.delete_after_print:
            lines.append('    <DELETEAFTERPRINT />')
        lines.append(f'    <Copies>{j.copies or 0}</Copies>')
        lines.append('  </PAGE>')
        lines.append('</WASATCH>')
        return '\n'.join(lines)

    def write_atomic(self, hotfolder_path: str) -> Path:
        dest = Path(hotfolder_path)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        filename = f'{stamp}_{_safe_name(self.job.name)}.xml'
        fd, tmp = tempfile.mkstemp(prefix=filename + '.', suffix='.tmp', dir=str(dest))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(self.to_xml())
                f.flush()
                os.fsync(f.fileno())
            final = dest / filename
            os.replace(tmp, final)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        logger.info('Wrote job XML %s', final)
        return final


def _esc(text: str) -> str:
    return escape(str(text))


def _tag_open(name: str, attrs: dict) -> str:
    parts = [f'{k}={v}' if k in ('ACTION',) else f'{k}="{v}"' for k, v in attrs.items()]
    joined = ' '.join([name] + parts)
    return f'<{joined}>'


def _safe_name(text: str) -> str:
    keep = [c if c.isalnum() or c in '-_' else '_' for c in text]
    return ''.join(keep)[:80] or 'job'


class WasatchLayoutXML:
    """Builds a <LAYOUT> of existing jobs, positioned in inches."""

    def __init__(self, layout, items):
        self.layout = layout
        self.items = items  # list of (LayoutItem, artwork Path)

    def to_xml(self) -> str:
        lay, items = self.layout, self.items
        lines = ['<?xml version="1.0" encoding="utf-8"?>', '<WASATCH ACTION=JOB>']
        attrs = ''
        if lay.notes:
            attrs = f' NOTES={_esc(lay.notes)}'
        lines.append(f'  <LAYOUT{attrs}>')
        lines.append(f'    <Copies>{lay.copies or 1}</Copies>')
        for item, art in items:
            j = item.job
            page_attrs = {'XPOSITION': f'{item.xposition:g}', 'YPOSITION': f'{item.yposition:g}'}
            lines.append('    ' + _tag_open('PAGE', page_attrs))
            lines.append(f'      <FileName>{_esc(str(art))}</FileName>')
            if item.rotate:
                lines.append(f'      <Rotate>{item.rotate}</Rotate>')
            if j.cut_bleed is not None:
                cut = f' Bleed={j.cut_bleed}'
                if j.cut_radius:
                    cut += f' Cornerradius={j.cut_radius}'
                lines.append(f'      <Cutoutline{cut}></Cutoutline>')
            # page copies zero: layout copies drive output
            lines.append('      <Copies>0</Copies>')
            lines.append('    </PAGE>')
        lines.append('  </LAYOUT>')
        lines.append('</WASATCH>')
        return '\n'.join(lines)

    def write_atomic(self, hotfolder_path: str) -> Path:
        dest = Path(hotfolder_path)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        filename = f'{stamp}_layout_{_safe_name(self.layout.name)}.xml'
        fd, tmp = tempfile.mkstemp(prefix=filename + '.', suffix='.tmp', dir=str(dest))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(self.to_xml())
                f.flush()
                os.fsync(f.fileno())
            final = dest / filename
            os.replace(tmp, final)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return final
