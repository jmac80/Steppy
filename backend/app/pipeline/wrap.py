"""Steppy's conversion: wrap the repaired mesh's triangles as a STEP BREP,
then fuse coplanar triangles into single clean faces (the FreeCAD-style
upgrade that makes the output actually pleasant to edit in CAD)."""

from __future__ import annotations

import numpy as np
import trimesh

from . import step_io


def faces_to_triangle_shapes(mesh: trimesh.Trimesh, face_indices: np.ndarray | None = None):
    """Build one flat triangular BRep face per selected mesh triangle."""
    faces = mesh.faces if face_indices is None else mesh.faces[face_indices]
    verts = mesh.vertices
    shapes = []
    for tri in faces:
        v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
        shape = step_io.triangle_face(v0, v1, v2)
        if shape is not None:
            shapes.append(shape)
    return shapes


def wrap_to_step(mesh: trimesh.Trimesh, out_path: str, unit: str = "MM",
                 preview_path: str | None = None) -> dict:
    shapes = faces_to_triangle_shapes(mesh)
    shape, is_solid, body_count = step_io.sew_faces(shapes, tolerance=1e-3)

    # FreeCAD-style upgrade: fuse coplanar triangles into single big faces,
    # so flat areas become one clean editable face each instead of triangle
    # soup. Curved areas keep their facets (they aren't coplanar). If the
    # merge ever fails, ship the unmerged shell -- faceted must always work.
    faces_before = len(shapes)
    faces_after = faces_before
    try:
        merged = step_io.unify_coplanar(shape)
        faces_after = step_io.count_faces(merged)
        if 0 < faces_after <= faces_before:
            shape = merged
        else:
            faces_after = faces_before
    except Exception:
        pass

    step_io.write_step(shape, out_path, unit=unit)

    has_preview = False
    if preview_path:
        try:
            step_io.write_preview_stl(shape, preview_path)
            has_preview = True
        except Exception:
            pass  # preview is a nice-to-have; never fail the conversion over it

    return {
        "mode": "faceted",
        "triangle_count": faces_before,
        "faces_after_merge": faces_after,
        "is_closed_solid": is_solid,
        "body_count": body_count,
        "preview": has_preview,
    }
