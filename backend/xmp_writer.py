"""XMP sidecar file writer, renamer, and deleter.

Uses Python stdlib xml.etree.ElementTree — no external dependencies.
Sidecar naming convention: photo.jpg.xmp (full filename + .xmp)

Written fields by mode:
  process_write_description → dc:description, tiff:ImageDescription
  process_write_tags        → dc:subject, digiKam:TagsList, lr:hierarchicalSubject
  (always when sidecar written) → exif:DateTimeOriginal, xmp:CreateDate, photoshop:DateCreated
"""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

# XMP namespace URIs
_NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "tiff": "http://ns.adobe.com/tiff/1.0/",
    "exif": "http://ns.adobe.com/exif/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "digiKam": "http://www.digikam.org/ns/1.0/",
    "lr": "http://ns.adobe.com/lightroom/1.0/",
}

# Register all namespaces so ET doesn't generate ns0/ns1 prefixes
for prefix, uri in _NS.items():
    ET.register_namespace(prefix, uri)


def _sidecar_path(image_path: Path) -> Path:
    """Return the XMP sidecar path for a given image file."""
    return image_path.parent / f"{image_path.name}.xmp"


def write_xmp_sidecar(
    image_path: Path,
    description: str | None = None,
    tags: list[str] | None = None,
    date: str | None = None,
) -> Path:
    """Write an XMP sidecar file next to the image. Returns the sidecar path.

    If the sidecar already exists it will be overwritten.
    Only writes fields that are provided (non-None).
    """
    xmpmeta = ET.Element(f"{{{_NS['x']}}}xmpmeta")
    rdf = ET.SubElement(xmpmeta, f"{{{_NS['rdf']}}}RDF")
    desc = ET.SubElement(rdf, f"{{{_NS['rdf']}}}Description")
    desc.set(f"{{{_NS['rdf']}}}about", "")

    # -- Description fields --
    if description:
        # dc:description as rdf:Alt with language tag
        dc_desc = ET.SubElement(desc, f"{{{_NS['dc']}}}description")
        alt = ET.SubElement(dc_desc, f"{{{_NS['rdf']}}}Alt")
        li = ET.SubElement(alt, f"{{{_NS['rdf']}}}li")
        li.set("{http://www.w3.org/XML/1998/namespace}lang", "x-default")
        li.text = description

        # tiff:ImageDescription (plain string — Immich reads this)
        tiff_desc = ET.SubElement(desc, f"{{{_NS['tiff']}}}ImageDescription")
        tiff_desc.text = description

    # -- Tag fields --
    if tags:
        # dc:subject (rdf:Bag) — standard XMP keywords
        dc_subject = ET.SubElement(desc, f"{{{_NS['dc']}}}subject")
        bag = ET.SubElement(dc_subject, f"{{{_NS['rdf']}}}Bag")
        for tag in tags:
            li = ET.SubElement(bag, f"{{{_NS['rdf']}}}li")
            li.text = tag

        # digiKam:TagsList (rdf:Seq) — Immich reads this
        dk_tags = ET.SubElement(desc, f"{{{_NS['digiKam']}}}TagsList")
        seq = ET.SubElement(dk_tags, f"{{{_NS['rdf']}}}Seq")
        for tag in tags:
            li = ET.SubElement(seq, f"{{{_NS['rdf']}}}li")
            li.text = tag

        # lr:hierarchicalSubject (rdf:Bag) — Lightroom compatibility
        lr_subj = ET.SubElement(desc, f"{{{_NS['lr']}}}hierarchicalSubject")
        bag2 = ET.SubElement(lr_subj, f"{{{_NS['rdf']}}}Bag")
        for tag in tags:
            li = ET.SubElement(bag2, f"{{{_NS['rdf']}}}li")
            li.text = tag

    # -- Date fields (written whenever a date is available) --
    if date:
        # exif:DateTimeOriginal — read by everything (Immich, Lightroom, digiKam, macOS Photos)
        exif_dto = ET.SubElement(desc, f"{{{_NS['exif']}}}DateTimeOriginal")
        exif_dto.text = date

        # xmp:CreateDate — XMP core, read by Lightroom, Immich, most modern tools
        xmp_cd = ET.SubElement(desc, f"{{{_NS['xmp']}}}CreateDate")
        xmp_cd.text = date

        # photoshop:DateCreated — IPTC mapping, read by Lightroom, IPTC-compliant tools
        ps_dc = ET.SubElement(desc, f"{{{_NS['photoshop']}}}DateCreated")
        ps_dc.text = date

    # Write to disk
    sidecar = _sidecar_path(image_path)
    tree = ET.ElementTree(xmpmeta)
    ET.indent(tree, space="  ")
    tree.write(sidecar, xml_declaration=True, encoding="UTF-8")

    logger.info("Wrote XMP sidecar: %s", sidecar.name)
    return sidecar


def rename_xmp_sidecar(old_image_path: Path, new_image_path: Path) -> bool:
    """Rename an XMP sidecar to match the new image filename.

    Returns True if a sidecar was found and renamed, False otherwise.
    """
    old_sidecar = _sidecar_path(old_image_path)
    if not old_sidecar.exists():
        return False

    new_sidecar = _sidecar_path(new_image_path)
    try:
        os.rename(old_sidecar, new_sidecar)
        logger.info("Renamed sidecar: %s → %s", old_sidecar.name, new_sidecar.name)
        return True
    except OSError as exc:
        logger.warning("Failed to rename sidecar %s: %s", old_sidecar, exc)
        return False


def delete_xmp_sidecar(image_path: Path) -> bool:
    """Delete the XMP sidecar for an image.

    Returns True if a sidecar was found and deleted, False otherwise.
    """
    sidecar = _sidecar_path(image_path)
    if not sidecar.exists():
        return False

    try:
        sidecar.unlink()
        logger.info("Deleted sidecar: %s", sidecar.name)
        return True
    except OSError as exc:
        logger.warning("Failed to delete sidecar %s: %s", sidecar, exc)
        return False
