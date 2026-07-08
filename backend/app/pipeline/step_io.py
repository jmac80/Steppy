
from __future__ import annotations

from OCP.gp import gp_Pnt
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
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain


def pnt(p) -> gp_Pnt:
    return gp_Pnt(float(p[0]), float(p[1]), float(p[2]))


def triangle_face(v0, v1, v2) -> TopoDS_Shape | None:
    poly = BRepBuilderAPI_MakePolygon(pnt(v0), pnt(v1), pnt(v2), True)
    if not poly.IsDone():
        return None
    face_maker = BRepBuilderAPI_MakeFace(poly.Wire())
    if not face_maker.IsDone():
        return None
    return face_maker.Face()


def sew_faces(faces: list[TopoDS_Shape], tolerance: float = 0.05) -> tuple[TopoDS_Shape, bool, int]:
    sewing = BRepBuilderAPI_Sewing(tolerance)
    for f in faces:
        if f is not None:
            sewing.Add(f)
    sewing.Perform()
    sewed = sewing.SewedShape()

    bodies = []
    all_closed = True
    explorer = TopExp_Explorer(sewed, TopAbs_SHELL)
    while explorer.More():
        shell = TopoDS.Shell_s(explorer.Current())
        solid_maker = BRepBuilderAPI_MakeSolid(shell)
        if solid_maker.IsDone():
            bodies.append(solid_maker.Solid())
        else:
            bodies.append(shell)
            all_closed = False
        explorer.Next()

    if not bodies:
        return sewed, False, 0
    if len(bodies) == 1:
        return bodies[0], all_closed, 1

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for b in bodies:
        builder.Add(compound, b)
    return compound, all_closed, len(bodies)


def count_faces(shape: TopoDS_Shape) -> int:
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    n = 0
    while explorer.More():
        n += 1
        explorer.Next()
    return n


def unify_coplanar(shape: TopoDS_Shape, linear_tol: float = 1e-4,
                    angular_tol_rad: float = 1e-2) -> TopoDS_Shape:
    unifier = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    unifier.SetLinearTolerance(linear_tol)
    unifier.SetAngularTolerance(angular_tol_rad)
    unifier.Build()
    return unifier.Shape()


def write_preview_stl(shape: TopoDS_Shape, out_path: str, quality: float = 0.004) -> None:
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
