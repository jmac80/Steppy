"""Top-level orchestrator: repair the upload, run the faceted wrap-and-merge
conversion, and assemble one report describing what happened.

Steppy deliberately does ONE conversion well: repair the mesh, wrap its
triangles as a STEP BREP, and fuse coplanar triangles into single clean
faces (the same upgrade FreeCAD applies, via OCCT's UnifySameDomain).
A prismatic surface-fitting mode existed previously and lives in the git
history if it's ever wanted again.
"""

from __future__ import annotations

import time

from . import repair, wrap


SUPPORTED_MODES = ("faceted",)


def convert(input_path: str, out_paths: dict, modes: list[str], unit: str = "MM",
            preview_paths: dict | None = None) -> dict:
    """
    out_paths: {mode_name: output_step_path} for every mode in `modes`
    preview_paths: {mode_name: preview_stl_path} -- optional; when present,
                   each mode also writes a lightweight mesh of its OUTPUT
                   shape so the browser can show a 3D before/after preview
    """
    preview_paths = preview_paths or {}
    t0 = time.time()
    mesh, repair_report = repair.load_and_repair(input_path)
    t_repair = time.time()

    results = {"repair": repair_report.as_dict(), "modes": {}}

    for mode in modes:
        if mode not in SUPPORTED_MODES:
            results["modes"][mode] = {"error": f"unknown mode '{mode}'"}
            continue

        t_start = time.time()
        try:
            mode_result = wrap.wrap_to_step(mesh, out_paths[mode], unit=unit,
                                            preview_path=preview_paths.get(mode))
            mode_result["seconds"] = round(time.time() - t_start, 2)
            results["modes"][mode] = mode_result
        except Exception as exc:
            results["modes"][mode] = {"error": str(exc)}

    results["repair_seconds"] = round(t_repair - t0, 2)
    results["total_seconds"] = round(time.time() - t0, 2)
    return results
