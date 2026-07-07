# Steppy
A simple self-hosted STL → STEP converter. Drop an STL in, get back a clean
STEP solid with flat areas merged into single editable faces.
## How to run it
You need Docker with the Compose plugin (any Linux distro, or Docker Desktop
on Mac/Windows).

    git clone https://github.com/jmac80/Steppy.git
    cd Steppy
    docker compose pull
    docker compose up -d

Then open **http://localhost:8642** in your browser (or `http://<server-ip>:8642`
from another machine on the network).
To use a different port, edit the `ports:` line in `docker-compose.yml`.
That's it. (Prefer building from source? Use `docker compose up -d --build` instead of the pull.)
## What Steppy does:
- Repairs the mesh (fills holes, fixes normals, removes degenerate triangles)
- Wraps it as a STEP BREP solid
- Fuses coplanar triangles into single flat faces, so the STEP is actually
  pleasant to edit in CAD instead of triangle city
- Shows a 3D preview of both the input STL and the converted output
- Keeps outputs numbered (`part-01.step`, `part-02.step`, ...) so nothing
  overwrites
Everything runs locally on your own machine — files never leave your network.
