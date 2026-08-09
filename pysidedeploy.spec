[app]
title = Research RAG
project_dir = .
input_file = run_gui.py
exec_directory = build/deploy
project_file =
icon =

[python]
python_path =
packages = Nuitka==4.1.3

[qt]
qml_files =
excluded_qml_plugins =
modules = Core,Gui,Widgets
plugins =

[android]
jars_dir =
ndk_path =
sdk_path =
recipe_dir =

[nuitka]
macos.permissions =
mode = standalone
extra_args = --quiet --noinclude-qt-translations --assume-yes-for-downloads --lto=no --macos-app-name="Research RAG"

[buildozer]
mode = debug
recipe_dir =
jars_dir =
ndk_path =
sdk_path =
