
from __future__ import annotations

import os

import trimesh

MAX_FACES = int(os.environ.get("MAX_FACES", "2000000"))


class RepairReport:
    def __init__(self):
        self.original_face_count = 0
        self.final_face_count = 0
        self.was_watertight_before = False
        self.was_watertight_after = False
        self.filled_holes = 0
        self.removed_degenerate_faces = 0
        self.notes: list[str] = []

    def as_dict(self):
        return {
            "original_face_count": self.original_face_count,
            "final_face_count": self.final_face_count,
            "was_watertight_before": self.was_watertight_before,
            "was_watertight_after": self.was_watertight_after,
            "filled_holes": self.filled_holes,
            "removed_degenerate_faces": self.removed_degenerate_faces,
            "notes": self.notes,
        }


def load_and_repair(path: str) -> tuple[trimesh.Trimesh, RepairReport]:
    report = RepairReport()
    mesh = trimesh.load(path, force="mesh")

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("Uploaded file did not resolve to a triangle mesh -- is it a valid STL?")

    report.original_face_count = len(mesh.faces)
    report.was_watertight_before = bool(mesh.is_watertight)

    mesh.merge_vertices()

    before_faces = len(mesh.faces)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    report.removed_degenerate_faces = before_faces - len(mesh.faces)

    if len(mesh.faces) == 0:
        raise ValueError("No usable triangles found in this file -- is it a valid STL?")
    if len(mesh.faces) > MAX_FACES:
        raise ValueError(
            f"This mesh has {len(mesh.faces):,} triangles; Steppy's limit is {MAX_FACES:,}. "
            "Simplify/decimate it in your slicer or mesh tool first."
        )

    mesh.fix_normals()

    try:
        holes_before = len(mesh.faces)
        trimesh.repair.fill_holes(mesh)
        report.filled_holes = len(mesh.faces) - holes_before
    except Exception as exc:
        report.notes.append(f"fill_holes skipped: {exc}")

    report.final_face_count = len(mesh.faces)
    report.was_watertight_after = bool(mesh.is_watertight)
    if not report.was_watertight_after:
        report.notes.append(
            "mesh is still not watertight after repair -- conversion will proceed "
            "but the STEP may come out as an open shell rather than a closed solid"
        )

    return mesh, report
