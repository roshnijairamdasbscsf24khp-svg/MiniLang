"""Copies the compiler into docs/ so the website uses the same code as the desktop app. Run after changing minilang/."""
import os, shutil
dst = os.path.join("docs", "minilang")
shutil.rmtree(dst, ignore_errors=True)
os.makedirs(dst)
for f in os.listdir("minilang"):
    if f.endswith(".py") and f != "gui.py":          # gui.py needs Tkinter - not used in the browser
        shutil.copy(os.path.join("minilang", f), dst)
print("docs/minilang updated:", sorted(os.listdir(dst)))
