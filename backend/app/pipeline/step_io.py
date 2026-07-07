"""
Shared low-level helpers for building OCCT (OpenCASCADE) shapes and writing
STEP files, via the `cadquery-ocp` (OCP) bindings. This is the one module
that talks directly to the CAD kernel, so every other pipeline module works
with plain numpy arrays and only touches OCP through the functions here.

NOTE: OCP is not installable in the sandbox this code was authored in (no
network access there -- see README). It's written against the documented,
stable OCCT/OCP API used throughout the CadQuery/build123d ecosystem, but
has not been executed yet. Treat the first real `docker compose build` +
a real conversion as the actual integration test, and see README
"first run checklist" for what to check.
"""

from __future__ import annotations

import numpy as np

from OCP.gp import gp_Pnt, gp_Dir, gp_Ax3, gp_Ax2, gp_Vec, gp_Pln
from OCP.Geom import Geom_Plane, Geom_CylindricalSurface, Geom_SphericalSurface, Geom_Surface
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_Sewing,
    BRepBuilderAPI_MakeSolid,
)
from OCP.TopoDS import TopoDS, TopoDS_Shape, TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SHELL, TopAbs_FACE
from OCP.STEPControl import STEPControl_Writer, STEPControl_StepModelType
from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.Interface import Interface_Static
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.StlAPI import StlAPI_Writer
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.ShapeFix import ShapeFix_Face
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain


def pnt(p) -> gp_Pnt:
    return gp_Pnt(float(p[0]), float(p[1]), float(p[2]))


def direction(v) -> gp_Dir:
    return gp_Dir(float(v[0]), float(v[1]), float(v[2]))


def triangle_face(v0, v1, v2) -> TopoDS_Shape | None:
    """Build a flat triangular BRep face from three points (faceted-wrap mode)."""
    poly = BRepBuilderAPI_MakePolygon(pnt(v0), pnt(v1), pnt(v2), True)
    if not poly.IsDone():
        return None
    wire = poly.Wire()
    face_maker = BRepBuilderAPI_MakeFace(wire)
    if not face_maker.IsDone():
        return None
    return face_maker.Face()


def make_surface(kind: str, params: dict, seam_hint_points=None) -> Geom_Surface:
    """
    Untrimmed analytic surface from a fitted primitive's parameters.

    seam_hint_points (cylinder only): 3D points of the region this surface
    will be trimmed to. Cylinders have a parametric seam at u=0 (along the
    frame's X direction); if the trim boundary crosses that seam, pcurve
    building and trimming get flaky and faces come out wrong or rejected.
    We rotate the frame so the seam points AWAY from the patch (opposite its
    mean angular direction), so real-world partial cylinders never straddle it.
    """
    if kind == "plane":
        return Geom_Plane(gp_Ax3(pnt(params["point"]), direction(params["normal"])))
    if kind == "cylinder":
        axis_point = np.asarray(params["axis_point"], dtype=float)
        axis = np.asarray(params["axis"], dtype=float)
        axis = axis / np.linalg.norm(axis)
        xdir = None
        if seam_hint_points is not None and len(seam_hint_points) >= 3:
            ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
            u = np.cross(axis, ref)
            u /= np.linalg.norm(u)
            v = np.cross(axis, u)
            rel = np.asarray(seam_hint_points, dtype=float) - axis_point
            ang = np.arctan2(rel @ v, rel @ u)
            mean_vec = np.array([np.cos(ang).mean(), np.sin(ang).mean()])
            norm = np.linalg.norm(mean_vec)
            if norm > 1e-6:
                d = mean_vec[0] * u + mean_vec[1] * v
                d /= np.linalg.norm(d)
                xdir = -d  # seam opposite the patch's centre direction
        if xdir is not None:
            ax2 = gp_Ax2(pnt(axis_point), direction(axis), direction(xdir))
        else:
            ax2 = gp_Ax2(pnt(axis_point), direction(axis))
        return Geom_CylindricalSurface(gp_Ax3(ax2), float(params["radius"]))
    if kind == "sphere":
        ax3 = gp_Ax3(pnt(params["center"]), gp_Dir(0, 0, 1))
        return Geom_SphericalSurface(ax3, float(params["radius"]))
    raise ValueError(f"unknown primitive kind '{kind}'")


def polyline_wire(points) -> "TopoDS_Shape | None":
    """Closed wire of straight segments through the given 3D points, in order."""
    poly = BRepBuilderAPI_MakePolygon()
    for p in points:
        poly.Add(pnt(p))
    poly.Close()
    if not poly.IsDone():
        return None
    return poly.Wire()


def _loop_length(points) -> float:
    pts = np.asarray(points, dtype=float)
    diffs = np.diff(np.vstack([pts, pts[:1]]), axis=0)
    return float(np.linalg.norm(diffs, axis=1).sum())


def face_from_surface_and_loops(surface: Geom_Surface, loops_points: list,
                                 tolerance: float) -> TopoDS_Shape | None:
    """
    The heart of prismatic v2: a face on an analytic surface trimmed by the
    mesh region's REAL boundary loops (outer rim + holes), passed as lists of
    ordered 3D points. Points are the original mesh vertices, so adjacent
    patches share identical boundary geometry and sewing can stitch them.

    ShapeFix_Face then computes the surface pcurves for the polyline edges,
    classifies outer vs hole wires, and fixes orientations -- the standard
    OCCT recipe for reverse-engineered trimmed faces.

    An empty loops_points list means the region has no rim at all (a fully
    closed surface, e.g. a complete sphere): the face is the whole surface.
    """
    if not loops_points:
        face_maker = BRepBuilderAPI_MakeFace(surface, 1e-6)
        return face_maker.Face() if face_maker.IsDone() else None

    wires = []
    for pts in loops_points:
        if len(pts) < 3:
            continue
        w = polyline_wire(pts)
        if w is not None:
            wires.append((w, _loop_length(pts)))
    if not wires:
        return None
    wires.sort(key=lambda t: -t[1])  # longest (outer) first

    face_maker = BRepBuilderAPI_MakeFace(surface, wires[0][0], True)
    for w, _ in wires[1:]:
        face_maker.Add(w)
    if not face_maker.IsDone():
        return None

    fixer = ShapeFix_Face(face_maker.Face())
    fixer.SetPrecision(tolerance)
    fixer.SetMaxTolerance(max(tolerance * 10.0, 1e-3))
    fixer.Perform()
    return fixer.Face()


def sew_faces(faces: list[TopoDS_Shape], tolerance: float = 0.05) -> tuple[TopoDS_Shape, bool]:
    """
    Sew a list of faces into a shell, and try to close it into a solid.
    Returns (shape, is_closed_solid). If sewing can't close the shape into a
    valid solid (typical for v1 prismatic output on complex parts -- see
    README), the caller still gets back a valid open shell that STEP can
    represent, just flagged as not-a-solid so the UI can say so honestly.
    """
    sewing = BRepBuilderAPI_Sewing(tolerance)
    for f in faces:
        if f is not None:
            sewing.Add(f)
    sewing.Perform()
    sewed = sewing.SewedShape()

    explorer = TopExp_Explorer(sewed, TopAbs_SHELL)
    if explorer.More():
        shell = TopoDS.Shell_s(explorer.Current())
        solid_maker = BRepBuilderAPI_MakeSolid(shell)
        if solid_maker.IsDone():
            solid = solid_maker.Solid()
            return solid, True

    return sewed, False


def compound_of(faces: list[TopoDS_Shape]) -> TopoDS_Shape:
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for f in faces:
        if f is not None:
            builder.Add(compound, f)
    return compound


def face_area(face: TopoDS_Shape) -> float:
    """Surface area of a face -- used to sanity-check that a trimmed face's
    area roughly matches the mesh region it stands in for. A wildly-off area
    means the trim inverted (face became everything-BUT-the-region) or
    collapsed, and the caller should fall back to triangles instead."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return float(props.Mass())


def count_faces(shape: TopoDS_Shape) -> int:
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    n = 0
    while explorer.More():
        n += 1
        explorer.Next()
    return n


def unify_coplanar(shape: TopoDS_Shape, linear_tol: float = 1e-4,
                    angular_tol_rad: float = 1e-2) -> TopoDS_Shape:
    """
    Merge adjacent faces lying on the same surface into single big faces --
    OCCT's ShapeUpgrade_UnifySameDomain, the same operation FreeCAD applies
    after mesh conversion (why its STEP output is 'much easier to edit').
    On a faceted shell this fuses all coplanar triangles: flat areas become
    one clean face each, curved areas stay faceted. The tight angular
    tolerance (~0.6 degrees) means only genuinely coplanar facets merge --
    chamfers and shallow curves are never smoothed over.
    """
    unifier = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    unifier.SetLinearTolerance(linear_tol)
    unifier.SetAngularTolerance(angular_tol_rad)
    unifier.Build()
    return unifier.Shape()


def write_preview_stl(shape: TopoDS_Shape, out_path: str, quality: float = 0.004) -> None:
    """
    Triangulate the (possibly analytic) BREP shape and write a lightweight
    STL used purely for the browser's 3D preview of the *output* -- so the
    user can see what the converted STEP actually looks like without opening
    a CAD package. `quality` is the meshing deflection as a fraction of the
    shape's bounding-box diagonal (smaller = finer preview, bigger file).
    """
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        raise RuntimeError("shape has no extent; nothing to preview")
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    diag = ((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5
    deflection = max(diag * quality, 1e-4)

    BRepMesh_IncrementalMesh(shape, deflection, False, 0.5, True)

    writer = StlAPI_Writer()
    try:
        # binary STL is ~5x smaller; if this binding detail ever changes,
        # fall through silently and write the default ASCII instead.
        writer.ASCIIMode = False
    except Exception:
        pass
    if not writer.Write(shape, out_path):
        raise RuntimeError("preview STL write failed")


def write_step(shape: TopoDS_Shape, out_path: str, unit: str = "MM") -> None:
    Interface_Static.SetCVal_s("write.step.unit", unit)
    writer = STEPControl_Writer()
    status = writer.Transfer(shape, STEPControl_StepModelType.STEPControl_AsIs)
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise RuntimeError(f"STEP transfer failed with status {status}")
    status = writer.Write(out_path)
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise RuntimeError(f"STEP write failed with status {status}")
