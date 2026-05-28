"""Internal unified-diff applier (no shell, no external dependencies).

Used exclusively by :class:`~app.application.virtual_workspace.VirtualWorkspace`.
Exposed as a private module so external code imports via the workspace API.
"""
from __future__ import annotations

import re
from pathlib import Path


class PatchApplyError(Exception):
    """Raised when a unified diff hunk cannot be applied cleanly."""


def apply_unified_diff(work_dir: Path, diff_text: str) -> list[str]:
    """Apply *diff_text* (unified diff) to files under *work_dir*.

    Supports:
    - Standard ``--- a/path  +++ b/path`` headers.
    - Git extended headers ``diff --git a/path b/path``.
    - New-file and deleted-file hunks.

    Returns the list of relative paths that were modified/created/deleted.
    """
    if not diff_text.strip():
        return []

    file_patches = _split_into_file_patches(diff_text)
    changed: list[str] = []

    for rel_path, hunks, is_new, is_deleted in file_patches:
        abs_path = work_dir / rel_path

        if is_deleted:
            abs_path.unlink(missing_ok=True)
            changed.append(rel_path)
            continue

        # Read existing content (empty string for new files).
        if abs_path.exists():
            lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        else:
            lines = []

        for hunk in hunks:
            lines = _apply_hunk(lines, hunk, rel_path)

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text("".join(lines), encoding="utf-8")
        changed.append(rel_path)

    return changed


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_FILE_HEADER_RE = re.compile(
    r"^(?:diff --git a/\S+ b/\S+\n)?(?:(?:new|deleted) file mode \d+\n)?(?:index [^\n]+\n)?--- (.+)\n\+\+\+ (.+)",
    re.MULTILINE,
)
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def _split_into_file_patches(
    diff_text: str,
) -> list[tuple[str, list[list[str]], bool, bool]]:
    """Split a full diff into per-file (path, hunks, is_new, is_deleted) tuples."""
    results: list[tuple[str, list[list[str]], bool, bool]] = []

    # Split on "--- " lines that start a new file section.
    sections = re.split(r"(?=^--- )", diff_text, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section or not section.startswith("---"):
            continue

        lines_iter = iter(section.splitlines(keepends=True))
        orig_line = next(lines_iter, "")
        new_line = next(lines_iter, "")

        if not orig_line.startswith("---") or not new_line.startswith("+++"):
            continue

        orig_path = _strip_ab_prefix(orig_line[4:].strip())
        new_path = _strip_ab_prefix(new_line[4:].strip())

        is_new = orig_path == "/dev/null"
        is_deleted = new_path == "/dev/null"
        rel_path = new_path if not is_deleted else orig_path

        # Collect hunk lines.
        hunk_lines: list[str] = []
        hunks: list[list[str]] = []
        remainder = "".join(lines_iter)
        in_hunk = False

        for line in remainder.splitlines(keepends=True):
            if line.startswith("@@"):
                if in_hunk and hunk_lines:
                    hunks.append(hunk_lines)
                hunk_lines = [line]
                in_hunk = True
            elif in_hunk:
                hunk_lines.append(line)

        if in_hunk and hunk_lines:
            hunks.append(hunk_lines)

        results.append((rel_path, hunks, is_new, is_deleted))

    return results


def _strip_ab_prefix(path: str) -> str:
    """Remove ``a/`` or ``b/`` git prefix from a path."""
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _apply_hunk(lines: list[str], hunk: list[str], rel_path: str) -> list[str]:
    """Apply a single hunk to *lines* and return the updated list."""
    header = hunk[0]
    m = _HUNK_HEADER_RE.match(header)
    if not m:
        raise PatchApplyError(f"Cannot parse hunk header in '{rel_path}': {header!r}")

    orig_start = int(m.group(1)) - 1  # convert to 0-based
    orig_count = int(m.group(2)) if m.group(2) is not None else 1

    result = list(lines[:orig_start])
    orig_pos = orig_start

    for diff_line in hunk[1:]:
        if diff_line.startswith(" "):
            # Context line — must match.
            if orig_pos < len(lines):
                result.append(lines[orig_pos])
                orig_pos += 1
            else:
                result.append(diff_line[1:])  # tolerate EOF context
        elif diff_line.startswith("+"):
            result.append(diff_line[1:])
        elif diff_line.startswith("-"):
            orig_pos += 1  # skip original line
        elif diff_line.startswith("\\ No newline"):
            pass  # ignore POSIX no-newline marker
        else:
            # Bare line in hunk (shouldn't happen in valid diffs — pass through).
            result.append(diff_line)

    # Append everything after the hunk.
    result.extend(lines[orig_pos:])
    return result
