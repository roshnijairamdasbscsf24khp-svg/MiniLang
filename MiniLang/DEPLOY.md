# Deploying MiniLang (GitHub Pages) and submitting

The website lives in the **`docs/`** folder. It runs the *same* Python compiler in the browser (Pyodide), so the live
version behaves exactly like the desktop app (minus the Tkinter window). It needs no server and no build step.

## 1. Try the website on your own computer first
```powershell
cd docs
python -m http.server 8000
```
Open http://localhost:8000 (the first load takes a few seconds while Python loads in the browser; you need internet).
Opening `index.html` by double-click does **not** work, the browser blocks loading the files; use the command above.

## 2. Put the project on GitHub
1. On github.com click **New repository**, name it e.g. `mini-compiler`, set it to **Public**, and create it (no README).
2. In PowerShell, inside the project folder (the one that contains `main.py`):
```powershell
git init
git add .
git commit -m "MiniLang compiler"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/mini-compiler.git
git push -u origin main
```
(No git? Install it from git-scm.com, or use **Add file -> Upload files** on the repository page and drag the whole folder in.)

## 3. Turn on the live website
Repository -> **Settings -> Pages** -> *Build and deployment* -> Source: **Deploy from a branch** ->
Branch: **main**, folder: **/docs** -> **Save**.
After about a minute the page shows your live URL:

    https://YOUR-USERNAME.github.io/mini-compiler/

Open it, check that a sample compiles, and submit that URL together with the repository link.

## 4. If you change the compiler later
Run `python sync_web.py` (copies `minilang/` into `docs/minilang/`), then commit and push again.

## 5. Submission checklist (every member submits individually)
- [ ] GitHub repository link (public, or the teacher has access): `https://github.com/YOUR-USERNAME/mini-compiler`
- [ ] Live deployment URL: `https://YOUR-USERNAME.github.io/mini-compiler/`
- [ ] Contribution summary (below)

### Contribution summary (template: keep only what is true for YOU and add your own details)
> **Name:** ______  **Group:** ______
> - **Planning:** helped decide the language (types, if/while, error handling) and split the work.
> - **Implementation:** (e.g. lexer, parser, semantic analysis, code generation, optimizer, GUI, web version)
> - **Error handling:** (e.g. panic mode, phrase-level repair with configurable repairs and the `==` / `!=` / `<=` / `>=` choice, did-you-mean suggestions)
> - **UI/UX design:** (e.g. dark theme, animated syntax tree, Recovery page, flow graph)
> - **Testing:** wrote/ran the 100 automated tests, tested 500+ line programs and deep nesting.
> - **Deployment:** created the GitHub repository and enabled GitHub Pages for the live version.
