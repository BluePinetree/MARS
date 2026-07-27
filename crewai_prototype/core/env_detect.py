"""core/env_detect.py — capability-based Python environment detection + reproducibility metadata.

특정 이름(예: MARS)에 묶지 않고, 파이프라인 실행에 필요한 패키지를 갖춘 "적합한" 환경인지
능력(import 가능 여부)으로 판정한다.

import 시 부작용이 없고 표준 라이브러리만 사용한다(깨진/base 환경에서도 안전하게 import 가능,
crewai/torch를 로드하지 않음). 다음에서 공유된다:
  - harness/anchor_run.py          (헤드리스 실행 환경 가드)
  - api/routes/environments.py     (UI 선택용 환경 목록)
  - phases/phase3_execution.py     (재현성 메타데이터 기록)
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# 파이프라인 실행에 필요한 모듈(전부 import 가능해야 "적합").
REQUIRED_MODULES = ["crewai", "torch", "sklearn", "pandas", "dotenv"]

# 재현성 지문을 위해 버전을 기록할 패키지(설치돼 있으면 기록, 없으면 생략).
REPRO_PACKAGES = [
    "crewai", "crewai-tools", "torch", "torchvision", "timm",
    "scikit-learn", "numpy", "pandas", "scipy", "xgboost", "lightgbm", "openai",
]

_PROBE_TIMEOUT = 30  # 후보 인터프리터 검사 타임아웃(초). find_spec 선검사로 대부분 즉시 실패.
_PROBE_WORKERS = 12  # 후보 환경 병렬 프로빙 워커 수(시스템에 conda env가 많을 수 있음)


# ── 능력 기반 탐지 프리미티브 (anchor_run.py의 env 가드가 재사용) ─────────────
def current_env_suitable() -> bool:
    """현재 인터프리터가 필요한 모듈을 모두 import할 수 있는지 (in-process)."""
    for mod in REQUIRED_MODULES:
        try:
            __import__(mod)
        except Exception:
            return False
    return True


# find_spec로 "설치 여부"를 먼저 싸게 확인하고(모듈을 실제 실행하지 않음 → 빠름, 깨진
# DLL도 이 단계는 통과), 전부 설치돼 있을 때만 실제 __import__로 로드 가능 여부를 검증한다
# (base의 깨진 torch처럼 설치는 됐지만 import가 실패하는 경우를 잡아낸다).
_FASTPROBE_CODE = (
    "import importlib.util as u, sys\n"
    "req = " + json.dumps(REQUIRED_MODULES) + "\n"
    "try:\n"
    "    present = all(u.find_spec(m) is not None for m in req)\n"
    "except Exception:\n"
    "    present = False\n"
    "if not present:\n"
    "    sys.exit(1)\n"
    "for m in req:\n"
    "    try:\n"
    "        __import__(m)\n"
    "    except Exception:\n"
    "        sys.exit(1)\n"
    "sys.exit(0)\n"
)


def probe_python(py_exe) -> bool:
    """후보 인터프리터가 필요한 모듈을 모두 import 가능한지 별도 프로세스로 검사(find_spec 선검사)."""
    try:
        return subprocess.run(
            [str(py_exe), "-c", _FASTPROBE_CODE], capture_output=True, timeout=_PROBE_TIMEOUT
        ).returncode == 0
    except Exception:
        return False


def candidate_pythons() -> "list[Path]":
    """탐색 대상 conda 환경들의 python 실행파일 목록 (현재 인터프리터 제외)."""
    prefix = Path(sys.prefix)
    roots: set[Path] = {prefix if prefix.parent.name != "envs" else prefix.parent.parent}
    for var in ("CONDA_ROOT", "CONDA_PREFIX_1"):
        v = os.environ.get(var)
        if v:
            roots.add(Path(v))
    cands: list[Path] = []
    for root in roots:
        for exe in ("python.exe", "python"):
            base_py = root / exe
            if base_py.exists():
                cands.append(base_py)
            cands.extend(Path(p) for p in glob.glob(str(root / "envs" / "*" / exe)))
    cur = Path(sys.executable).resolve()
    seen: set[str] = set()
    out: list[Path] = []
    for c in cands:
        rc = c.resolve()
        if rc == cur or str(rc) in seen:
            continue
        seen.add(str(rc))
        out.append(rc)
    return out


def env_name(py_exe) -> str:
    """python 실행파일 경로에서 conda 환경 이름을 추출한다 (base 포함)."""
    p = Path(py_exe).resolve()
    parent = p.parent
    if parent.parent.name == "envs":
        return parent.name
    return "base"


def dedup_suitable(items):
    """(name, py) 튜플 목록에서 실행파일 경로 기준 중복 제거."""
    seen: set[str] = set()
    out = []
    for name, py in items:
        key = str(Path(py).resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append((name, py))
    return out


# ── UI/API용: 적합 환경 목록 ─────────────────────────────────────────────────
_PROBE_INFO_CODE = (
    "import importlib.util as u, json, sys\n"
    "req = " + json.dumps(REQUIRED_MODULES) + "\n"
    "missing = []\n"
    "for m in req:\n"
    "    try:\n"
    "        spec = u.find_spec(m)\n"
    "    except Exception:\n"
    "        spec = None\n"
    "    if spec is None:\n"
    "        missing.append(m)\n"
    "if not missing:\n"
    "    for m in req:\n"
    "        try:\n"
    "            __import__(m)\n"
    "        except Exception:\n"
    "            missing.append(m)\n"
    "print(json.dumps({'suitable': not missing, 'missing': missing, "
    "'python_version': sys.version.split()[0]}))\n"
)


def _probe_info(py_exe) -> dict:
    """후보 인터프리터를 한 번의 서브프로세스로 검사해 적합성/버전/누락모듈을 반환."""
    try:
        proc = subprocess.run(
            [str(py_exe), "-c", _PROBE_INFO_CODE],
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT,
        )
        lines = (proc.stdout or "").strip().splitlines()
        return json.loads(lines[-1]) if lines else {"suitable": False}
    except Exception:
        return {"suitable": False, "missing": list(REQUIRED_MODULES), "python_version": None}


def _importable(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def _dedup_dicts(items):
    seen: set[str] = set()
    out = []
    for e in items:
        key = str(Path(e["executable"]).resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def list_suitable_environments() -> "list[dict]":
    """UI 선택용 적합 환경 목록. 현재 인터프리터 + 후보 conda 환경들을 검사한다.

    각 항목: {name, executable, python_version, suitable, missing, is_current, recommended}
    적합한(suitable=True) 항목만 반환하며, 첫 항목(현재 환경 우선)이 recommended=True.
    """
    envs: list[dict] = []
    cur = Path(sys.executable).resolve()

    # 현재 인터프리터는 in-process로 빠르게 판정
    cur_missing = [m for m in REQUIRED_MODULES if not _importable(m)]
    envs.append({
        "name": env_name(cur),
        "executable": str(cur),
        "python_version": sys.version.split()[0],
        "suitable": not cur_missing,
        "missing": cur_missing,
        "is_current": True,
    })

    # 후보 conda 환경이 많을 수 있어(수십 개) 병렬로 프로빙한다.
    # find_spec 선검사로 필수 패키지가 없는 대부분의 환경은 즉시 탈락한다.
    cands = candidate_pythons()
    if cands:
        with ThreadPoolExecutor(max_workers=min(_PROBE_WORKERS, len(cands))) as ex:
            infos = list(ex.map(_probe_info, cands))
        for py, info in zip(cands, infos):
            envs.append({
                "name": env_name(py),
                "executable": str(py),
                "python_version": info.get("python_version"),
                "suitable": bool(info.get("suitable")),
                "missing": info.get("missing", []),
                "is_current": False,
            })

    suitable = _dedup_dicts([e for e in envs if e["suitable"]])
    for i, e in enumerate(suitable):
        e["recommended"] = (i == 0)  # 현재 환경 우선, 없으면 첫 적합 환경
    return suitable


# ── phase3용: 재현성 메타데이터 ──────────────────────────────────────────────
_DESCRIBE_CODE = (
    "import json, sys, platform\n"
    "try:\n"
    "    from importlib.metadata import version\n"
    "except Exception:\n"
    "    version = None\n"
    "pkgs = " + json.dumps(REPRO_PACKAGES) + "\n"
    "out = {'python_version': sys.version.split()[0], "
    "'python_full': ' '.join(sys.version.split()), "
    "'executable': sys.executable, 'platform': platform.platform(), 'packages': {}}\n"
    "if version is not None:\n"
    "    for p in pkgs:\n"
    "        try:\n"
    "            out['packages'][p] = version(p)\n"
    "        except Exception:\n"
    "            pass\n"
    "print(json.dumps(out))\n"
)


def describe_python(py_exe=None) -> dict:
    """주어진 python(기본: 현재 인터프리터)의 재현성 메타데이터를 수집한다.

    반환: {env_name, executable, python_version, python_full, platform, packages}
    실패 시 최소 정보(executable/env_name)라도 반환한다.
    """
    py = str(py_exe) if py_exe else sys.executable
    info: dict = {}
    try:
        proc = subprocess.run(
            [py, "-c", _DESCRIBE_CODE],
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT,
        )
        lines = (proc.stdout or "").strip().splitlines()
        if lines:
            info = json.loads(lines[-1])
    except Exception:
        info = {}
    if not isinstance(info, dict):
        info = {}
    info.setdefault("executable", py)
    info.setdefault("packages", {})
    info["env_name"] = env_name(py)
    return info


def requirements_hash(packages: dict) -> str:
    """패키지 버전 딕셔너리로부터 짧은 재현성 지문(sha256 앞 12자)."""
    if not packages:
        return ""
    blob = json.dumps(packages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
