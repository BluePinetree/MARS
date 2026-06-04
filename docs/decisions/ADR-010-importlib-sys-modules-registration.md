# ADR-010 — importlib Import Check: Register Module in sys.modules Before exec_module

**Date:** 2026-05-29  
**Status:** Accepted  
**Context:** `crewai_prototype/crew_tools/syntax_check_tool.py`

---

## Context

Phase 2's smoke test verifies that every generated Python file can be successfully
imported. The import check uses Python's `importlib` to load each file in
isolation without executing the experiment:

```python
spec = importlib.util.spec_from_file_location('_chk', path)
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)   # execute module-level code
```

This approach is preferred over spawning a subprocess because it is faster (no
process creation overhead), runs in the same Python environment, and produces
structured exception objects rather than stderr strings.

---

## Problem

Every file that used the `@dataclass` decorator failed the import check with a
`TypeError`, even when the file was syntactically correct and its class definitions
were valid:

```
TypeError: 'NoneType' object is not subscriptable
  File "src/config.py", line 8, in Config
    learning_rate: float = 1e-3
```

The error occurred *inside* the `@dataclass` decorator, not in the user-written
code. Investigation revealed the following chain:

1. `spec_from_file_location('_chk', path)` creates a module with `__name__ = '_chk'`.
2. `module_from_spec(spec)` creates the module object.
3. `exec_module(mod)` executes the module body — **but `mod` is not yet in `sys.modules`**.
4. When `@dataclass` decorates a class, it calls:
   ```python
   sys.modules.get(cls.__module__)   # cls.__module__ == '_chk'
   ```
   to resolve forward references for type annotations.
5. `sys.modules.get('_chk')` returns `None` because the module was never registered.
6. The dataclass machinery receives `None` as the module and attempts to access
   `.`-notation on it, producing `TypeError: 'NoneType' object...`

This is not documented in the Python `importlib` documentation. The standard
library's own `importlib.import_module()` handles registration automatically;
`spec.loader.exec_module()` used directly does not.

**Impact:** Any generated file using `@dataclass` (which is idiomatic for config,
results, and model parameter classes) would fail the import check. The repair loop
would repeatedly attempt to "fix" syntactically valid code.

---

## Decision

**Register the module in `sys.modules` under its name before calling `exec_module`,
and remove it after the check completes.**

```python
# crew_tools/syntax_check_tool.py — check_import()

spec = importlib.util.spec_from_file_location('_chk', path)
mod  = importlib.util.module_from_spec(spec)

sys.modules['_chk'] = mod           # register BEFORE exec_module
try:
    spec.loader.exec_module(mod)
    return CheckResult(passed=True)
except Exception as exc:
    return CheckResult(passed=False, error=str(exc), error_type=_classify(exc))
finally:
    sys.modules.pop('_chk', None)   # clean up — don't pollute the module namespace
```

The `finally` block ensures the temporary module is removed from `sys.modules`
regardless of success or failure, preventing contamination of subsequent import
checks.

---

## Consequences

**Positive**

- **All `@dataclass`-decorated files pass import check.** The fix is one line and
  structural — it mirrors what `importlib.import_module()` does internally.
- **No false-positive repair attempts.** The repair loop no longer attempts to
  "fix" valid `@dataclass` files.
- **Cleanup via `finally`.** The temporary `_chk` module does not persist in
  `sys.modules` between checks, preventing cross-file contamination (e.g., if
  `config.py` and `models.py` both use `_chk` as the temp name).

**Negative / Trade-offs**

- **Isolation is partial.** The import check runs in the same process, so
  side effects from `exec_module` (e.g., module-level `print()` calls, file writes)
  execute in the main process. Mitigated: generated experiment code should not
  have module-level side effects; this is enforced in the generation prompt.
- **`_chk` is a fixed name.** If two import checks run concurrently (possible if
  Phase 2 were parallelized), they would collide on `sys.modules['_chk']`.
  Currently not an issue because file generation is sequential. A UUID-based
  name would fix this if parallelization is added later.

---

## Engineering Lesson

> `importlib.util.spec_from_file_location` + `exec_module` is not a drop-in
> replacement for `importlib.import_module`. The key difference: `import_module`
> registers the module in `sys.modules` before executing it; `exec_module` does
> not. Any module-level code that inspects `sys.modules` at decoration or
> initialization time — including `@dataclass`, `@attrs.define`, and any
> metaclass-based framework — will fail unless the module is pre-registered.

This is undocumented behavior as of Python 3.12. It affects any testing or
validation framework that uses `exec_module` for isolated module loading.

---

## Related

- [DEVLOG 2026-05-29](../DEVLOG.md#2026-05-29-bug-dataclass-files-always-fail-import-check) — investigation and fix
- `crewai_prototype/crew_tools/syntax_check_tool.py` — `check_import()`
- [ADR-008](ADR-008-repair-loop-escalation.md) — this fix prevented false-positive escalations in the repair loop
