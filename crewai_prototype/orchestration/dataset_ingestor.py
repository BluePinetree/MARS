"""orchestration/dataset_ingestor.py — 사용자 제공 데이터 폴더 조사·압축해제·구조 추론 (Phase 0b).

data_path가 주어지면 실행: 폴더를 도구로 조사 → 압축(zip/tar/gz) 자동 감지·안전 해제 →
구조 추론(ImageFolder / CSV / parquet / timeseries / train-test) → dataset_manifest.json 산출.
그 manifest를 planner/designer/coder에 주입하면 LLM이 실제 경로/컬럼/클래스를 보고 코드를 생성한다.

설계 원칙(전문가 회의 2026-07-28):
- 결정론적·읽기 위주(도구 기반). LLM 불필요 → 네트워크 없이 동작·검증 가능.
- 아래 도구 함수(list_tree/read_head/detect_archives/extract_archive/probe_dataset)는
  나중에 LLM tool-loop(에이전트가 직접 호출)이 그대로 재사용하도록 순수 함수로 노출한다.
- 보안: Zip-Slip/심볼릭링크 탈출 방어, 파일 수·크기 상한.
"""
from __future__ import annotations

import csv
import os
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".ppm"}
_ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
_TARGET_NAME_HINTS = ("label", "labels", "target", "class", "y", "output",
                      "survived", "churn", "outcome", "category", "species")
_TS_NAME_HINTS = ("date", "time", "timestamp", "datetime", "ds", "month", "day", "period")

_MAX_EXTRACT_FILES = 50000
_MAX_EXTRACT_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB
_MAX_LIST_ENTRIES = 2000


# ── 도구: 폴더 트리 조사 ──────────────────────────────────────────────────────
def list_tree(root: str | Path, max_depth: int = 3, max_entries: int = _MAX_LIST_ENTRIES) -> dict:
    """폴더를 재귀 조사해 파일 수·확장자 분포·상위 디렉토리·총 크기를 반환한다."""
    root = Path(root)
    ext_counts: dict[str, int] = {}
    n_files = 0
    total_bytes = 0
    top_dirs: list[str] = []
    truncated = False
    if root.is_dir():
        top_dirs = sorted([p.name for p in root.iterdir() if p.is_dir()])[:200]
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= max_depth:
            dirnames[:] = []  # 더 깊이 안 감
        for fn in filenames:
            n_files += 1
            if n_files > max_entries:
                truncated = True
                continue
            ext = Path(fn).suffix.lower()
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            try:
                total_bytes += (Path(dirpath) / fn).stat().st_size
            except OSError:
                pass
    return {
        "root": str(root),
        "n_files": n_files,
        "top_dirs": top_dirs,
        "ext_counts": dict(sorted(ext_counts.items(), key=lambda kv: -kv[1])),
        "total_size_mb": round(total_bytes / 1024 / 1024, 2),
        "truncated": truncated,
    }


# ── 도구: 파일 앞부분 읽기 (CSV 헤더 등) ──────────────────────────────────────
def read_head(path: str | Path, n_lines: int = 5, max_bytes: int = 8192) -> str:
    """텍스트 파일의 앞부분(최대 n_lines/ max_bytes)을 반환한다."""
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            out: list[str] = []
            read = 0
            for i, line in enumerate(f):
                if i >= n_lines or read >= max_bytes:
                    break
                out.append(line.rstrip("\n"))
                read += len(line)
            return "\n".join(out)
    except Exception as exc:  # noqa: BLE001
        return f"(read_head 실패: {exc})"


# ── 도구: 압축 감지 ──────────────────────────────────────────────────────────
def detect_archives(root: str | Path) -> "list[str]":
    """폴더 최상위의 아카이브 파일(zip/tar/gz…) 경로 목록."""
    root = Path(root)
    if not root.is_dir():
        return []
    found: list[str] = []
    for p in root.iterdir():
        if p.is_file():
            name = p.name.lower()
            if p.suffix.lower() in _ARCHIVE_EXTS or name.endswith(".tar.gz") or name.endswith(".tar.bz2"):
                found.append(str(p))
    return sorted(found)


# ── 도구: 안전한 압축 해제 (Zip-Slip / 심볼릭링크 방어) ───────────────────────
def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def extract_archive(archive: str | Path, dest: str | Path) -> dict:
    """아카이브를 dest로 안전 해제한다. Zip-Slip/심볼릭링크 탈출·과대 크기를 방어한다."""
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    total = 0
    count = 0
    try:
        if archive.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    target = dest / info.filename
                    if not _is_within(dest, target):
                        return {"ok": False, "error": f"Zip-Slip 차단: {info.filename}"}
                    count += 1
                    total += info.file_size
                    if count > _MAX_EXTRACT_FILES or total > _MAX_EXTRACT_BYTES:
                        return {"ok": False, "error": "압축 해제 크기/파일수 상한 초과"}
                zf.extractall(dest)
        elif name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".gz", ".bz2", ".xz")):
            mode = "r:*"
            with tarfile.open(archive, mode) as tf:
                members = tf.getmembers()
                for m in members:
                    target = dest / m.name
                    if m.issym() or m.islnk():
                        return {"ok": False, "error": f"심볼릭/하드링크 멤버 차단: {m.name}"}
                    if not _is_within(dest, target):
                        return {"ok": False, "error": f"경로 탈출 차단: {m.name}"}
                    count += 1
                    total += m.size
                    if count > _MAX_EXTRACT_FILES or total > _MAX_EXTRACT_BYTES:
                        return {"ok": False, "error": "압축 해제 크기/파일수 상한 초과"}
                tf.extractall(dest)
        else:
            return {"ok": False, "error": f"지원하지 않는 아카이브: {archive.name}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"해제 실패: {exc}"}
    return {"ok": True, "dest": str(dest), "n_members": count}


# ── 도구: 데이터셋 구조 추론 ─────────────────────────────────────────────────
def _looks_like_imagefolder(root: Path) -> "tuple[bool, list[str]]":
    """하위 디렉토리들이 각각 이미지 파일을 담으면 ImageFolder로 간주."""
    subdirs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))]
    class_dirs: list[str] = []
    for d in subdirs:
        try:
            has_img = any(f.suffix.lower() in _IMAGE_EXTS for f in d.iterdir() if f.is_file())
        except OSError:
            has_img = False
        if has_img:
            class_dirs.append(d.name)
    return (len(class_dirs) >= 2, sorted(class_dirs))


def _sniff_csv(path: Path) -> dict:
    """CSV 헤더/구분자/컬럼/행수/target·timestamp 추정."""
    info: dict = {"path": str(path), "columns": [], "delimiter": ",", "n_rows": None}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            sample = f.read(8192)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            info["delimiter"] = dialect.delimiter
        except csv.Error:
            info["delimiter"] = ","
        header_line = sample.splitlines()[0] if sample.splitlines() else ""
        cols = [c.strip() for c in header_line.split(info["delimiter"])]
        info["columns"] = cols
        # 행수(헤더 제외) — 라인 카운트
        with path.open("r", encoding="utf-8", errors="replace") as f:
            info["n_rows"] = max(sum(1 for _ in f) - 1, 0)
        # target 컬럼 추정: 이름 힌트 우선, 없으면 마지막 컬럼
        lowers = [c.lower() for c in cols]
        target = None
        for hint in _TARGET_NAME_HINTS:
            for c, lc in zip(cols, lowers):
                if lc == hint or lc.endswith("_" + hint) or lc == hint + "s":
                    target = c
                    break
            if target:
                break
        if not target and cols:
            target = cols[-1]
        info["target_column"] = target
        # timestamp 컬럼 추정: 이름 힌트
        ts = None
        for c, lc in zip(cols, lowers):
            if any(h in lc for h in _TS_NAME_HINTS):
                ts = c
                break
        info["timestamp_column"] = ts
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
    return info


def probe_dataset(root: str | Path) -> dict:
    """폴더 구조를 추론해 profile_hint와 스키마 힌트를 담은 dict를 반환한다."""
    root = Path(root)
    result: dict = {"resolved_path": str(root), "format": "unknown",
                    "profile_hint": "generic_script", "probed": True, "notes": ""}
    if not root.is_dir():
        result["format"] = "missing"
        result["probed"] = False
        result["notes"] = "경로가 존재하지 않거나 폴더가 아님"
        return result

    entries = list(root.iterdir())
    files = [p for p in entries if p.is_file()]
    csvs = [p for p in files if p.suffix.lower() == ".csv"]
    parquets = [p for p in files if p.suffix.lower() in (".parquet", ".pq")]
    npzs = [p for p in files if p.suffix.lower() in (".npz", ".npy")]

    # 1) ImageFolder
    is_img, classes = _looks_like_imagefolder(root)
    if is_img:
        result.update(format="imagefolder", profile_hint="vision_classification",
                      classes=classes, n_classes=len(classes))
        result["notes"] = f"이미지 폴더(클래스 {len(classes)}개) 감지"
        return result

    # 1b) train/test 하위 폴더가 ImageFolder인 경우
    for split in ("train", "training"):
        sub = root / split
        if sub.is_dir():
            si, sc = _looks_like_imagefolder(sub)
            if si:
                result.update(format="imagefolder", profile_hint="vision_classification",
                              classes=sc, n_classes=len(sc), split_dir=split)
                result["notes"] = f"{split}/ 하위 이미지 폴더(클래스 {len(sc)}개) 감지"
                return result

    # 2) CSV
    if csvs:
        # train.csv 우선
        primary = next((c for c in csvs if c.stem.lower() in ("train", "training", "data")), csvs[0])
        sniff = _sniff_csv(primary)
        is_ts = bool(sniff.get("timestamp_column"))
        result.update(
            format="csv",
            profile_hint="timeseries_forecasting" if is_ts else "tabular_supervised",
            primary_csv=str(primary),
            columns=sniff.get("columns", []),
            target_column=sniff.get("target_column"),
            timestamp_column=sniff.get("timestamp_column"),
            n_rows=sniff.get("n_rows"),
            delimiter=sniff.get("delimiter"),
            csv_files=[c.name for c in csvs],
        )
        result["notes"] = (
            f"CSV 감지: target≈{sniff.get('target_column')}"
            + (f", timestamp≈{sniff.get('timestamp_column')}" if is_ts else "")
        )
        return result

    # 3) parquet / npz
    if parquets:
        result.update(format="parquet", profile_hint="tabular_supervised",
                      parquet_files=[p.name for p in parquets])
        result["notes"] = "parquet 감지 (tabular)"
        return result
    if npzs:
        result.update(format="npz", profile_hint="generic_script",
                      npz_files=[p.name for p in npzs])
        result["notes"] = "npz/npy 배열 감지 (generic)"
        return result

    result["notes"] = "구조를 특정하지 못함 — data_description을 활용하세요"
    return result


# ── 드라이버: 조사 → 해제 → 추론 → manifest ──────────────────────────────────
def ingest(
    data_path: str | Path,
    data_description: str = "",
    emit: Optional[Callable[[str, str, dict], None]] = None,
) -> dict:
    """data_path를 조사해 dataset_manifest(dict)를 만든다.

    - 아카이브만 있고 직접 쓸 구조가 없으면 `<data_path>/_mars_extracted/`로 안전 해제 후 그쪽을 조사.
    - 반환 manifest의 resolved_path가 실제 데이터 루트(실행 CLI/DATA_DIR에 넘길 경로).
    """
    def _emit(msg: str, meta: Optional[dict] = None) -> None:
        if emit:
            emit("AGENT_MESSAGE", f"[Phase 0b] {msg}", meta or {})

    root = Path(data_path)
    manifest: dict[str, Any] = {
        "input_path": str(root),
        "resolved_path": str(root),
        "data_description": data_description or "",
        "extracted_from": None,
    }
    if not root.exists():
        manifest.update(format="missing", profile_hint="generic_script", probed=False,
                        notes="경로가 존재하지 않음")
        _emit(f"데이터 경로 없음: {root}", manifest)
        return manifest

    tree = list_tree(root)
    manifest["tree"] = tree
    _emit(f"폴더 조사: 파일 {tree['n_files']}개, 확장자 {list(tree['ext_counts'])[:6]}, "
          f"{tree['total_size_mb']}MB", {"tree": tree})

    # 직접 사용할 구조가 있는지 먼저 확인
    probe = probe_dataset(root)

    # 구조 불명 + 아카이브 존재 → 해제 후 재조사
    if probe.get("format") in ("unknown", "missing"):
        archives = detect_archives(root)
        if archives:
            dest = root / "_mars_extracted"
            _emit(f"아카이브 {len(archives)}개 감지 → 안전 해제: {Path(archives[0]).name}",
                  {"archives": [Path(a).name for a in archives]})
            ext = extract_archive(archives[0], dest)
            if ext.get("ok"):
                # 해제 결과에 단일 최상위 폴더가 있으면 그쪽을 루트로
                sub = [p for p in dest.iterdir() if p.is_dir()]
                probe_root = sub[0] if len(sub) == 1 else dest
                probe = probe_dataset(probe_root)
                manifest["extracted_from"] = Path(archives[0]).name
                manifest["resolved_path"] = str(probe_root)
                _emit(f"해제 완료 → 재조사: {probe.get('format')} ({probe.get('notes')})", probe)
            else:
                _emit(f"압축 해제 실패: {ext.get('error')}", ext)
                manifest["extract_error"] = ext.get("error")

    # probe 결과 병합 (resolved_path는 위에서 갱신됐을 수 있음)
    probe.pop("resolved_path", None)
    manifest.update(probe)
    _emit(f"구조 추론 완료: format={manifest.get('format')} "
          f"profile={manifest.get('profile_hint')}", {"manifest_summary": _summary(manifest)})
    return manifest


def _summary(manifest: dict) -> str:
    """manifest를 프롬프트/로그용 짧은 문자열로."""
    parts = [f"format={manifest.get('format')}", f"profile={manifest.get('profile_hint')}",
             f"path={manifest.get('resolved_path')}"]
    if manifest.get("classes"):
        parts.append(f"classes({manifest.get('n_classes')})={manifest['classes'][:10]}")
    if manifest.get("columns"):
        parts.append(f"columns={manifest['columns'][:15]}")
    if manifest.get("target_column"):
        parts.append(f"target={manifest['target_column']}")
    if manifest.get("timestamp_column"):
        parts.append(f"timestamp={manifest['timestamp_column']}")
    if manifest.get("n_rows") is not None:
        parts.append(f"n_rows={manifest['n_rows']}")
    if manifest.get("extracted_from"):
        parts.append(f"extracted_from={manifest['extracted_from']}")
    return " | ".join(parts)


def manifest_to_context(manifest: dict) -> str:
    """manifest를 codegen 프롬프트에 넣을 지시문으로 변환."""
    lines = ["DETECTED DATASET (probed from the user-provided folder — use these EXACT facts):",
             f"- resolved data root: {manifest.get('resolved_path')} "
             "(read via os.environ['DATA_DIR'] or --data-path; do NOT download)",
             f"- format: {manifest.get('format')} / suggested profile: {manifest.get('profile_hint')}"]
    if manifest.get("classes"):
        lines.append(f"- image classes ({manifest.get('n_classes')}): {manifest['classes'][:20]}")
    if manifest.get("columns"):
        lines.append(f"- columns: {manifest['columns'][:30]}")
    if manifest.get("target_column"):
        lines.append(f"- target column (predict this): {manifest['target_column']}")
    if manifest.get("timestamp_column"):
        lines.append(f"- timestamp column: {manifest['timestamp_column']}")
    if manifest.get("n_rows") is not None:
        lines.append(f"- rows: {manifest['n_rows']}")
    if manifest.get("delimiter"):
        lines.append(f"- csv delimiter: '{manifest['delimiter']}'")
    if manifest.get("extracted_from"):
        lines.append(f"- (auto-extracted from archive: {manifest['extracted_from']})")
    if manifest.get("data_description"):
        lines.append(f"- user note: {manifest['data_description']}")
    return "\n".join(lines)
