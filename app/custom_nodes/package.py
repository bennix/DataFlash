"""Install custom node packages from zip or raw files."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from .loader import (
    BUNDLE_AI_SAMPLE_DIR,
    BUNDLE_SAMPLE_DIR,
    custom_nodes_root,
    load_custom_node,
    node_dir,
    validate_id,
    validate_package_dir,
)


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.endswith("/") or not name:
            continue
        # Zip slip protection
        target = (dest / name).resolve()
        if not str(target).startswith(str(dest.resolve())):
            raise ValueError(f"非法压缩路径：{info.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as out:
            shutil.copyfileobj(src, out)


def _normalize_extracted_root(extracted: Path) -> Path:
    """If zip has a single top-level folder containing manifest, use that."""
    if (extracted / "manifest.json").is_file() and (extracted / "transform.py").is_file():
        return extracted
    children = [p for p in extracted.iterdir() if not p.name.startswith(".")]
    dirs = [p for p in children if p.is_dir()]
    if len(dirs) == 1 and (dirs[0] / "manifest.json").is_file():
        return dirs[0]
    # Search one level
    for child in dirs:
        if (child / "manifest.json").is_file() and (child / "transform.py").is_file():
            return child
    raise FileNotFoundError("zip 中未找到 manifest.json + transform.py")


def install_from_zip(instance_path: str | Path, zip_bytes: bytes) -> dict:
    custom_nodes_root(instance_path)
    with tempfile.TemporaryDirectory(prefix="dataflash-cnode-") as tmp:
        extracted = Path(tmp) / "extracted"
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            _safe_extract_zip(zf, extracted)
        package = _normalize_extracted_root(extracted)
        meta, _ = validate_package_dir(package)
        custom_id = validate_id(str(meta["id"]))
        dest = node_dir(instance_path, custom_id)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(package, dest)
        # Ensure manifest id matches folder
        meta["id"] = custom_id
        (dest / "manifest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    spec = load_custom_node(instance_path, custom_id)
    return {
        "id": spec.custom_id,
        "type": spec.type,
        "label": spec.label,
        "description": spec.description,
    }


def install_from_files(
    instance_path: str | Path,
    *,
    manifest_text: str,
    transform_text: str,
) -> dict:
    custom_nodes_root(instance_path)
    with tempfile.TemporaryDirectory(prefix="dataflash-cnode-") as tmp:
        package = Path(tmp) / "pkg"
        package.mkdir()
        (package / "manifest.json").write_text(manifest_text, encoding="utf-8")
        (package / "transform.py").write_text(transform_text, encoding="utf-8")
        meta, _ = validate_package_dir(package)
        custom_id = validate_id(str(meta["id"]))
        dest = node_dir(instance_path, custom_id)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(package, dest)
        meta["id"] = custom_id
        (dest / "manifest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    spec = load_custom_node(instance_path, custom_id)
    return {
        "id": spec.custom_id,
        "type": spec.type,
        "label": spec.label,
        "description": spec.description,
    }


def sample_zip_bytes() -> bytes:
    return _bundle_zip(BUNDLE_SAMPLE_DIR, "scale_numeric")


def sample_ai_zip_bytes() -> bytes:
    return _bundle_zip(BUNDLE_AI_SAMPLE_DIR, "ai_flag_rows")


def _bundle_zip(bundle: Path, arc_root: str) -> bytes:
    if not bundle.is_dir():
        raise FileNotFoundError(f"内置样例包缺失：{arc_root}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{arc_root}/{path.relative_to(bundle)}")
    return buf.getvalue()
