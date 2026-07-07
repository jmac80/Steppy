"""
Mesh loading + repair, built on trimesh (installed in the Docker image; not
available in the dev sandbox this was authored in -- see README "How this was
tested" for what was and wasn't run before first real deployment).
"""

from __future__ import annotations

import trimesh


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


def load_and_repair(path: str, decimate_target_faces: int | None = None) -> tuple[trimesh.Trimesh, RepairReport]:
    """
    Load an STL (binary or ASCII) and run standard repair steps:
      - merge duplicate vertices
      - fix inconsistent winding / normals
      - fill small holes
      - drop degenerate / zero-area triangles
      - optional decimation for very dense scan meshes

    Returns the repaired mesh plus a report describing what was done, which
    the API surfaces to the user (this is the "auto mesh repair" QoL feature).
    """
    report = RepairReport()
    mesh = trimesh.load(path, force="mesh")

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("Uploaded file did not resolve to a single triangle mesh")

    report.original_face_count = len(mesh.faces)
    report.was_watertight_before = bool(mesh.is_watertight)

    mesh.merge_vertices()

    before_faces = len(mesh.faces)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    report.removed_degenerate_faces = before_faces - len(mesh.faces)

    mesh.fix_normals()

    try:
        holes_before = len(mesh.faces)
        trimesh.repair.fill_holes(mesh)
        report.filled_holes = len(mesh.faces) - holes_before
    except Exception as exc:  # pragma: no cover - defensive, trimesh repair can be finicky
        report.notes.append(f"fill_holes skipped: {exc}")

    if decimate_target_faces and len(mesh.faces) > decimate_target_faces:
        try:
            mesh = mesh.simplify_quadric_decimation(face_count=decimate_target_faces)
            report.notes.append(
                f"decimated dense mesh down to ~{decimate_target_faces} faces"
            )
        except Exception as exc:  # pragma: no cover
            report.notes.append(f"decimation skipped: {exc}")

    report.final_face_count = len(mesh.faces)
    report.was_watertight_after = bool(mesh.is_watertight)
    if not report.was_watertight_after:
        report.notes.append(
            "mesh is still not watertight after repair -- conversion will proceed "
            "but the STEP may come out as an open shell rather than a closed solid"
        )

    return mesh, report
