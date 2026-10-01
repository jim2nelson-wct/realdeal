import logging
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

from .status_config import SOFRIP_HTTP_URL, SOFRIP_HTTP_TIMEOUT

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


def _parse(xml_text: str) -> ET.Element | None:
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("SoftRIP returned invalid XML: %s", e)
        return None


def get_system() -> dict:
    """Returns {'online': bool, 'name': str, 'serial': str, 'units': [{'number','name'}]}"""
    resp = _get("xmlSystem.dyn")
    if resp is None:
        return {"online": False, "name": None, "serial": None, "units": []}
    root = _parse(resp.text)
    if root is None:
        return {"online": True, "name": None, "serial": None, "units": []}
    units = [
        {"number": u.get("number"), "name": u.get("name")}
        for u in root.findall("PRINTUNIT")
    ]
    return {"online": True, "name": root.get("name"), "serial": root.get("sn"), "units": units}


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
