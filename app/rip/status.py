import logging
import os
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

from .status_config import SOFRIP_HTTP_URL, SOFRIP_HTTP_TIMEOUT

__all__ = ["SOFRIP_HTTP_URL", "SOFRIP_HTTP_TIMEOUT", "get_system", "get_imgconfs",
           "get_queue", "analyze_url_or_path", "confirm_in_rip_queue",
           "confirm_in_print_queue", "layout_print_progress", "clear_queue", "reprint_by_index"]

logger = logging.getLogger(__name__)


def _get(path: str, params: dict | None = None):
    try:
        resp = requests.get(f"{SOFRIP_HTTP_URL.rstrip('/')}/{path.lstrip('/')}",
                            params=params, timeout=SOFRIP_HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        logger.warning("SoftRIP HTTP request failed: %s (%s)", path, e)
        return None


def confirm_in_rip_queue(unit: str, artwork_path: str, attempts: int = 6, delay: float = 1.0) -> str:
    """Poll the RIP queue watch for our source file. One of 'confirmed'|'offline'|'pending'."""
    target = os.path.normcase(os.path.normpath(artwork_path))
    for _ in range(max(1, attempts)):
        q = get_queue(unit)
        if not q["available"]:
            return "offline"
        for item in q["ripqueue"]:
            src = item.get("sourcefile") or ""
            if os.path.normcase(os.path.normpath(src)) == target:
                return "confirmed"
        time.sleep(delay)
    return "pending"


def confirm_in_print_queue(unit: str, attempts: int = 6, delay: float = 1.0) -> str:
    """Poll the print queue watch for a layout job whose output copies has gone up.

    One of 'confirmed'|'offline'|'pending'.
    """
    for _ in range(max(1, attempts)):
        q = get_queue(unit)
        if not q["available"]:
            return "offline"
        for item in q["printqueue"]:
            output = str(item.get("output", "")).strip()
            digits = "".join(ch for ch in output if ch.isdigit())
            if str(item.get("layout", "")).lower() == "true" and digits.isdigit() and int(digits) > 0:
                return "confirmed"
        time.sleep(delay)
    return "pending"


def layout_print_progress(unit: str) -> str:
    """Single snapshot check: 'confirmed' if a layout job on the unit has output copies, else 'offline'|'pending'."""
    return confirm_in_print_queue(unit, attempts=1, delay=0.0)


def _post_xml(xml: str) -> bool:
    try:
        resp = requests.post(SOFRIP_HTTP_URL.rstrip('/'), data=xml.encode('utf-8'),
                             headers={'Content-Type': 'text/xml'}, timeout=SOFRIP_HTTP_TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.warning("SoftRIP XML POST failed: %s", e)
        return False


def reprint_by_index(unit: str, indexes: list, copies: int = 1) -> bool:
    """Reprint already-ripped print queue entries by index via PRINTQUEUE action XML."""
    blocks = ''.join(
        f'<PRINTQUEUE><INDEX>{_esc(i)}</INDEX><Copies>{copies}</Copies></PRINTQUEUE>'
        for i in indexes)
    xml = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<WASATCH ACTION=JOB><PRINTUNIT>{_esc(unit)}</PRINTUNIT>{blocks}</WASATCH>')
    return _post_xml(xml)


def clear_queue(unit: str, queue: str) -> bool:
    """Clear the RIP or print queue of a unit via a SYSTEM action XML.

    queue: 'rip' clears the RIP queue, 'print' clears the print queue.
    """
    tag = 'CLEARRIPQUEUE' if queue == 'rip' else 'CLEARPRINTQUEUE'
    xml = (f'<?xml version="1.0" encoding="utf-8"?>\n'
           f'<WASATCH ACTION=SYSTEM>\n'
           f'\t<{tag} PRINTUNIT="{unit}" />\n'
           f'</WASATCH>')
    return _post_xml(xml)


def _parse(xml_text: str) -> ET.Element | None:
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("SoftRIP returned invalid XML: %s", e)
        return None


def get_system() -> dict:
    """Returns {'online': bool, 'name': str, 'serial': str, 'qpa': bool, 'units': [...]}"""
    resp = _get("xmlSystem.dyn")
    if resp is None:
        return {"online": False, "name": None, "serial": None, "qpa": None, "units": []}
    root = _parse(resp.text)
    if root is None:
        return {"online": True, "name": None, "serial": None, "qpa": None, "units": []}
    units = [
        {"number": u.get("number"), "name": u.get("name")}
        for u in root.findall("PRINTUNIT")
    ]
    qpa_attr = root.get("qpa")
    return {
        "online": True,
        "name": root.get("name"),
        "serial": root.get("sn"),
        "qpa": None if qpa_attr is None else qpa_attr.lower() == "true",
        "units": units,
    }


def get_imgconfs(unit: str) -> list[str]:
    """List available imaging configurations for a print unit."""
    resp = _get("xmlImgConfStatus.dyn", {"PRINTUNIT": unit})
    if resp is None:
        return []
    root = _parse(resp.text)
    if root is None:
        return []
    return [node.text.strip() for node in root.iter("IMGCONF") if node.text and node.text.strip()]


def get_queue(unit: str) -> dict:
    """RIP queue and print queue summaries for a unit."""
    resp = _get("xmlQueueStatus.dyn", {"PRINTUNIT": unit})
    if resp is None:
        return {"available": False, "ripqueue": [], "printqueue": []}
    root = _parse(resp.text)
    if root is None:
        return {"available": False, "ripqueue": [], "printqueue": []}

    def rip_items(q):
        return [it.attrib for it in q.findall("ITEM")]

    def print_items(q):
        items = []
        for it in q.findall("ITEM"):
            item = dict(it.attrib)
            logs = it.findall("LOG")
            item["logs"] = [log.attrib for log in logs]
            items.append(item)
        return items

    rip = root.find("RIPQUEUE")
    prt = root.find("PRINTQUEUE")
    return {
        "available": True,
        "ripqueue": rip_items(rip) if rip is not None else [],
        "printqueue": print_items(prt) if prt is not None else [],
    }


def analyze_url_or_path(location: str) -> dict | None:
    """Page count and size of an input file, via sourceAnalysis.dyn."""
    quoted = quote(location, safe="/\\:")
    resp = _get(f"sourceAnalysis.dyn?{quoted}")
    if resp is None:
        return None
    root = _parse(resp.text)
    if root is None:
        return None
    pagecount = root.findtext("PAGECOUNT")
    width = root.findtext("WIDTH")
    height = root.findtext("HEIGHT")
    return {
        "pages": int(pagecount) if pagecount and pagecount.isdigit() else 1,
        "width": float(width) if width else None,
        "height": float(height) if height else None,
    }
