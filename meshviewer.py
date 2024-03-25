"""SolidPython/STL/OBJ Python Mesh Viewer prototype with Vispy
using a Model View Controller (MVC) design.

This is just a simple prototype/proof-of-concept and not intended to
be a full fledged application. 

:license: AGPL v3, see LICENSE for more details.

:copyright: 
    2020 Precise Simulation Ltd.
    2023 Emilio Moretti

"""
from typing import override

try:
    import tkinter as tk
except ImportError:
    import Tkinter as tk

import importlib.util
import logging
import pathlib
import subprocess
import time
import tkinter.font as tkfont
import tkinter.ttk as ttk
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Lock
from tkinter.filedialog import askopenfilename

import vispy
import vispy.scene
from solid2 import scad_render_to_file
from watchdog.events import DirDeletedEvent, FileModifiedEvent, LoggingEventHandler
from watchdog.observers import Observer

# import vispy.visuals
vispy.use(app="tkinter")

import os
import sys

import numpy as np

# polling reload on the UI
UI_RELOAD_TIME = 1000

# prevent re-reloading a file if watchdog decides to notify us twice for one edit
MINIMUM_RELOAD_TIME = timedelta(milliseconds=UI_RELOAD_TIME)


if os.name == "nt":
    from ctypes import pointer, windll, wintypes

    try:
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass  # this will fail on Windows Server and maybe early Windows


class Model:
    def __init__(self, file_name=None):
        self.data = []
        if file_name is None:
            # Define unit cube.
            vertices = [
                [0, 1, 0],
                [1, 1, 0],
                [1, 0, 0],
                [0, 0, 0],
                [1, 0, 1],
                [0, 0, 1],
                [1, 1, 1],
                [0, 1, 1],
            ]
            faces = [
                [0, 1, 2],
                [0, 2, 3],
                [2, 4, 5],
                [2, 5, 3],
                [4, 2, 1],
                [4, 1, 6],
                [6, 1, 0],
                [6, 0, 7],
                [3, 5, 7],
                [3, 7, 0],
                [6, 5, 4],
                [6, 7, 5],
            ]
            data = Mesh(
                np.asarray(vertices, dtype="float32"), np.asarray(faces, dtype="uint32")
            )

            self.data = [data]
        else:
            self.load_file(file_name)

    def clear(self):
        self.data = []

    def load_file(self, file_name):
        """Load mesh from file"""
        vertices, faces, _, _ = vispy.io.read_mesh(file_name)
        self.data.append(Mesh(vertices, faces))

    def get_bounding_box(self):
        bbox = self.data[0].bounding_box
        for mesh in self.data[1:]:
            for i in range(len(bbox)):
                x_i = mesh.bounding_box[i]
                bbox[i][0] = min([bbox[i][0], min(x_i)])
                bbox[i][1] = max([bbox[i][1], max(x_i)])

        return bbox


class Mesh:
    def __init__(self, vertices, faces):
        self.vertices = vertices
        self.faces = faces
        self.bounding_box = self.get_bounding_box()

    def get_vertices(self):
        vertices = []
        for face in self.faces:
            vertices.append([self.vertices[ivt] for ivt in face])

        return vertices

    def get_line_segments(self):
        line_segments = set()
        for face in self.faces:
            for i in range(len(face)):
                iv = face[i]
                jv = face[(i + 1) % len(face)]
                if jv > iv:
                    edge = (iv, jv)
                else:
                    edge = (jv, iv)

                line_segments.add(edge)

        return [
            [self.vertices[edge[0] - 1], self.vertices[edge[1] - 1]]
            for edge in line_segments
        ]

    def get_bounding_box(self):
        v = [vti for face in self.get_vertices() for vti in face]
        bbox = []
        for i in range(len(self.vertices[0])):
            x_i = [p[i] for p in v]
            bbox.append([min(x_i), max(x_i)])

        return bbox


class View:
    def __init__(self, model=None):
        if model is None:
            model = Model()
        self.model = model
        self.canvas = None
        self.vpview = None

    def clear(self):
        if self.vpview is not None:
            self.vpview.parent = None

        self.vpview = self.canvas.central_widget.add_view(bgcolor="white")
        vispy.scene.visuals.XYZAxis(parent=self.vpview.scene)

    def plot(self, types="solid + wireframe"):
        self.clear()
        if isinstance(types, (str,)):
            types = [s.strip() for s in types.split("+")]

        for mesh in self.model.data:
            for type in types:
                if type == "solid":
                    msh = vispy.scene.visuals.Mesh(
                        vertices=mesh.vertices, shading="smooth", faces=mesh.faces
                    )
                    self.vpview.add(msh)

                elif type == "wireframe":
                    n_faces = len(mesh.faces)
                    ix = np.tile([0, 1, 1, 2, 2, 0], n_faces) + np.repeat(
                        np.arange(0, 3 * n_faces, 3), 6
                    )
                    edges = mesh.faces.reshape(-1)[ix]
                    edg = vispy.scene.visuals.Line(
                        pos=mesh.vertices[edges], connect="segments"
                    )
                    self.vpview.add(edg)

                else:
                    # Unknown plot type
                    return None

        self.vpview.camera = vispy.scene.TurntableCamera(parent=self.vpview.scene)

    def xy(self):
        self.vpview.camera.elevation = 90
        self.vpview.camera.azimuth = -90
        self.vpview.camera.roll = 0

    def xz(self):
        self.vpview.camera.elevation = 0
        self.vpview.camera.azimuth = -90
        self.vpview.camera.roll = 0

    def yz(self):
        self.vpview.camera.elevation = 0
        self.vpview.camera.azimuth = 0
        self.vpview.camera.roll = 0

    def reset(self):
        self.vpview.camera.reset()


class Controller:
    def __init__(self, view=None, file_name=None):
        default_handler = self.DefaultFileHandler(self)
        self.file_handlers = defaultdict(lambda: default_handler)
        self.file_handlers[".py"] = self.PythonFileHandler(self)
        self.file_handlers[".scad"] = self.ScadFileHandler(self)
        root = tk.Tk()
        root.geometry("600x550")
        root.title("Mesh Viewer")
        self.reload_lock = Lock()
        self.reload_file = None

        if view is None:
            view = View()

        f1 = ttk.Frame(root)
        f1.pack(side=tk.TOP, anchor=tk.W)

        toolbar = [
            tk.Button(f1, text="Open"),
            tk.Button(f1, text="XY", command=view.xy),
            tk.Button(f1, text="XZ", command=view.xz),
            tk.Button(f1, text="YZ", command=view.yz),
            tk.Button(f1, text="Reset", command=view.reset),
        ]

        f2 = tk.Frame(f1, highlightthickness=1, highlightbackground="gray")
        options = ["solid", "wireframe", "solid + wireframe"]
        self.view_mode_var = tk.StringVar()
        o1 = ttk.OptionMenu(
            f2,
            self.view_mode_var,
            options[len(options) - 1],
            *options,
            command=lambda val: self.view.plot(val),
        )
        o1["menu"].configure(bg="white")
        setMaxWidth(options, o1)
        o1.pack()
        toolbar.append(f2)

        toolbar[0].config(command=lambda: self.open())

        [obj.pack(side=tk.LEFT, anchor=tk.W) for obj in toolbar]

        canvas = vispy.scene.SceneCanvas(keys="interactive", show=True, parent=root)
        canvas.native.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        view.canvas = canvas
        root.update_idletasks()

        menubar = tk.Menu(root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open...", command=lambda: self.open())
        file_menu.add_command(label="Exit", command=self.exit)
        menubar.add_cascade(label="File", menu=file_menu)
        root.config(menu=menubar)

        self.root = root
        self.view = view
        self.model = view.model
        self.root_frame = f1
        view.plot()

    def render(self):
        self.root.mainloop()

    def get_file_handler(self, path):
        return self.file_handlers[pathlib.Path(path).suffix]

    def open(self):
        file_name = askopenfilename(
            title="Select file to open",
            filetypes=(
                ("SolidPython file", "*.py"),
                ("CAD files", "*.obj *.stl"),
                ("all files", "*.*"),
            ),
        )
        self.file_handler = self.get_file_handler(file_name)
        self.file_handler.reload(file_name)
        # Start observing file for changes after loading it, to avoid a double reload
        self.file_handler.follow(file_name)
        # start the loop that checks if we have to reload
        self.file_reloader()

    def file_reloader(self):
        """
        This code executes in the main thread thanks to frame.after().
        The observer will signal us to reload the model, because doing
        it from the observer's thread breaks vispy.
        """
        if self.reload_lock.acquire(blocking=False):
            if self.reload_file:
                print("Processing reload signal")
                self.load_file_in_viewer(self.reload_file)
            self.reload_file = None
            self.reload_lock.release()
        self.root_frame.after(UI_RELOAD_TIME, self.file_reloader)

    def load_file_in_viewer(self, file_handle):
        self.model.clear()
        self.model.load_file(file_handle)
        self.view.plot(self.view_mode_var.get())

    def exit(self):
        if hasattr(self, 'file_handler'):
            self.file_handler.stop()
        self.model.clear()
        self.view.clear()
        self.root.destroy()

    class BaseFileHandler(LoggingEventHandler):
        def __init__(self, controller):
            super().__init__()
            self.controller = controller
            self.observer = None
            self.observed_file = None
            self.observed_path = None
            self.observer_watch = None
            self.last_reload = None

        def follow(self, observed_file):
            """
            Follows a file by observing the parent directory.

            Following the file didn't work since sometimes it got deleted and replaced,
            which broke the internal observer state and forced me to re-create it.
            """
            if self.observer:
                self.observer.unschedule(self.observed_file)
                self.observer.stop()
                self.observer.join()
            self.observer = Observer()
            self.observed_file = observed_file
            self.observed_path = pathlib.Path(observed_file).parents[0]
            self.observer_watch = None
            self.observer_watch = self.observer.schedule(
                self, self.observed_path, recursive=False
            )
            self.observer.start()
            self.last_reload = datetime.now()
            self.logger.info("Following %s", self.observed_path)

        def stop(self):
            if self.observer:
                self.observer.stop()
                self.observer.join()

        def reload(self):
            """
            File dependent implementation
            """
            raise NotImplemented()

    class DefaultFileHandler(BaseFileHandler):
        @override
        def reload(self, file_path):
            # By default just load the file in the viewer
            if self.controller.reload_lock.acquire(blocking=True):
                self.logger.info("Sending reload signal")
                self.controller.reload_file = file_path
                self.controller.reload_lock.release()

        @override
        def on_modified(self, event):
            super().on_modified(event)
            if (
                isinstance(event, FileModifiedEvent)
                and event.src_path == self.observed_file
            ):
                # log the event and reload the file
                now = datetime.now()
                if now - self.last_reload > MINIMUM_RELOAD_TIME:
                    self.last_reload = now
                    self.reload(event.src_path)

    class ScadFileHandler(DefaultFileHandler):
        @override
        def reload(self, file_path):
            # call openscad and generate an stl, then load the stl
            file_handle = pathlib.Path(file_path)
            new_file = file_handle.with_stem("solidpython_temp").with_suffix(".stl")
            try:
                subprocess.run(["openscad", "-o", new_file, file_path])
            except FileNotFoundError as _:
                subprocess.run(["openscad-nightly", "-o", new_file, file_path])
            self.logger.info(f"Converted scad file to {new_file}")
            super().reload(new_file)

    class PythonFileHandler(ScadFileHandler):
        @override
        def reload(self, file_path):
            file_handle = pathlib.Path(file_path)
            new_path = file_handle.with_stem("solidpython_temp").with_suffix(".scad")
            spec = importlib.util.spec_from_file_location(
                "tmp.solidpython.model", file_path
            )
            foo = importlib.util.module_from_spec(spec)
            # sys.modules["module.name"] = foo
            spec.loader.exec_module(foo)
            new_file = scad_render_to_file(
                foo.solidpython_model,
                filename=new_path,
                file_header=f"$fn = {foo.solidpython_segments};",
            )
            self.logger.info(f"Converted python file to {new_file}. Reloading STL...")
            super().reload(new_file)


def setMaxWidth(stringList, element):
    try:
        f = tkfont.nametofont(element.cget("font"))
        zerowidth = f.measure("0")
    except:
        f = tkfont.nametofont(ttk.Style().lookup("TButton", "font"))
        zerowidth = f.measure("0") - 0.8

    w = max([f.measure(i) for i in stringList]) / zerowidth
    element.config(width=int(w))


class App:
    def __init__(self, model=None, view=None, controller=None):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.event_handler = LoggingEventHandler()
        # TODO: properly parse arguments instead of this
        file_name = None
        if len(sys.argv) >= 2:
            file_name = sys.argv[1]

        if model is None:
            model = Model(file_name)

        if view is None:
            view = View(model)

        if controller is None:
            controller = Controller(view, file_name)

        self.model = model
        self.view = view
        self.controller = controller

    def start(self):
        self.controller.render()


if __name__ == "__main__":
    app = App()
    app.start()
