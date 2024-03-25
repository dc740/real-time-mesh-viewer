SolidPython realtime model visualizer

![tkinter UI screenshot](/screenshot.png?raw=true "Screenshot")

Use your favorite IDE to write python code, and get previews in real time as if you were using OpenSCAD (*).

This tkinter UI reloads and preview SolidPython (and .STL) models when they change on disk. 

It has three modes:
* STL viewer
* SCAD viewer (file is auto-converted to STL)
* .py file viewer (file auto-converted to SCAD and then to STL)

The model will be refreshed automatically in all cases when the original file gets updated.
The only requirement in python is for the model to expose these two variables:

    solidpython_model
    solidpython_segments

The example "basic_geometry.py" (taken from SolidPython) shows how to expose these two variables for the viewer to pick them up and update the view.


The original viewer code came from this other project, and I added the main feature on top of it:
https://github.com/precise-simulation/mesh-viewer/

(*) This was just a proof of concept. After all, it's easier to just start OpenSCAD, open the generated scad file (from SolidPython), and enable auto reload in _Design_ -> _Automatic Reload and Preview.

If converting a file takes a lot of time in OpenSCAD, then it will also take a lot of time to load on this project, but since it will be shown much smoother since they are automatically converted to STL files. Try reducing the number of segments, since this speeds up the process.

-----


To run it make sure you have OpenSCAD in your system PATH and start the script:

    python meshviewer.py

If vispy refuses to start because of EGL, GL or similar errors, try setting the backend with PYOPENGL_PLATFORM environment variable:

    PYOPENGL_PLATFORM=glx python meshviewer.py


Tested on _Ubuntu_. The typing module requires _Python 3.12_, but it could be removed to use older versions.

Licensed as AGPL, since this is the original license of the UI that this is based on.
