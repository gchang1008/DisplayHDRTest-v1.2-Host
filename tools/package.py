"""Build self-contained Windows x64 Host and Client ZIPs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
from zipfile import ZipFile, ZIP_DEFLATED

VERSION = "3.13.16"
RUNTIME_URL = f"https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip"
RUNTIME_SHA256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"
QT_VERSION = "6.11.1"
QT_WHEELS = (
    ("pyside6_essentials-6.11.1-cp310-abi3-win_amd64.whl",
     "https://files.pythonhosted.org/packages/64/0e/b663ecc96ca57b5c91b83b6615d6b174380b0faf30338125c26e053d6aa7/",
     "63311bd48e32c584599ab04b9ef7c324082374cd2c9fa533f978fb893bb47e40"),
    ("shiboken6-6.11.1-cp310-abi3-win_amd64.whl",
     "https://files.pythonhosted.org/packages/52/b5/3f6fb2ee65b534193fb4ef713dd619dc31dadff5d12c16979a7699ad58be/",
     "c2c6863aa80ec18c0f82cea3417837b279cdc60024ac17123461dc9042577df7"),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_qt(cache, runtime):
    destination = runtime / "Lib/site-packages"
    modules = {"QtCore", "QtGui", "QtWidgets", "QtTest"}
    binaries = {"pyside6.abi3.dll", "shiboken6.abi3.dll", "Shiboken.pyd", "concrt140.dll"}
    binaries.update(f"Qt6{module[2:]}.dll" for module in modules)
    for filename, base_url, expected in QT_WHEELS:
        archive = cache / filename
        if not archive.exists():
            urllib.request.urlretrieve(base_url + filename, archive)
        if digest(archive) != expected:
            raise RuntimeError(f"Qt wheel SHA-256 mismatch: {filename}")
        with ZipFile(archive) as source:
            for name in source.namelist():
                path = Path(name)
                if name.endswith("/"):
                    continue
                root = path.parts[0]
                keep = ".dist-info/" in name and ("/licenses/" in name or path.name == "METADATA")
                if root in ("PySide6", "shiboken6"):
                    keep |= path.suffix == ".py" and "scripts" not in path.parts
                    keep |= len(path.parts) == 2 and (path.name in binaries
                              or path.stem in modules or path.name.startswith(("msvcp140", "vcruntime140")))
                    keep |= name in ("PySide6/plugins/platforms/qwindows.dll", "PySide6/plugins/platforms/qoffscreen.dll",
                                     "PySide6/plugins/styles/qmodernwindowsstyle.dll")
                if keep:
                    source.extract(name, destination)
    licenses = runtime.parent / "licenses/Qt"
    licenses.mkdir(parents=True)
    for name in ("LGPL-3.0-only.txt", "GPL-3.0-only.txt", "Qt-GPL-exception-1.0.txt"):
        cached = cache / name
        if not cached.exists():
            urllib.request.urlretrieve(f"https://code.qt.io/cgit/qt/qtbase.git/plain/LICENSES/{name}?h=v6.11.1", cached)
        shutil.copy2(cached, licenses / name)


def main():
    repo = Path(__file__).resolve().parents[1]
    workspace = repo.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=workspace / "build-output/automation-x64-Release")
    parser.add_argument("--output", type=Path, default=workspace / "packages")
    args = parser.parse_args()
    cache = workspace / "build-output/package-cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"python-{VERSION}-embed-amd64.zip"
    if not archive.exists():
        urllib.request.urlretrieve(RUNTIME_URL, archive)
    if digest(archive) != RUNTIME_SHA256:
        raise RuntimeError("Embedded Python archive SHA-256 does not match the official release.")
    executable = args.release / "DisplayHDRComplianceTests.exe"
    if not executable.is_file():
        raise FileNotFoundError(executable)
    args.output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="portable-package-", dir=cache.parent))
    # Only clean the newly created stage after verifying its workspace boundary.
    if not stage.resolve().is_relative_to((workspace / "build-output").resolve()):
        raise RuntimeError("Package stage is outside build-output.")
    try:
        packages = []
        for role in ("Host", "Client"):
            folder = stage / f"DisplayHDR_{role}_x64"
            runtime = folder / "runtime"
            runtime.mkdir(parents=True)
            with ZipFile(archive) as source:
                source.extractall(runtime)
            # Isolated runtime: standard library, bundled extensions, application folder.
            (runtime / "python313._pth").write_text("python313.zip\n.\n..\n", encoding="ascii")
            if role == "Client":
                bundle_qt(cache, runtime)
                (runtime / "python313._pth").write_text("python313.zip\n.\n..\nLib/site-packages\n", encoding="ascii")
            files = ("displayhdr_api.py", "displayhdr_server.py", "StartDisplayHDR.cmd") if role == "Host" else ("displayhdr_remote.py", "displayhdr_gui.py", "ControlDisplayHDR.cmd", "StartDisplayHDRClient.cmd")
            for name in files:
                shutil.copy2(repo / "tools" / name, folder / name)
            if role == "Host":
                shutil.copy2(executable, folder / executable.name)
                for extension in ("*.cso", "*.png"):
                    for resource in args.release.glob(extension):
                        shutil.copy2(resource, folder / resource.name)
                required = ("BackgroundNoiseEffect.cso", "BandedGradientEffect.cso", "SineSweepEffect.cso",
                            "ToneSpikeEffect.cso", "CalibriBoth96Dpi.png", "OnePixelLinesBW1200x700.png", "OnePixelLinesRG1200x700.png")
                for name in required:
                    if not (folder / name).is_file():
                        raise FileNotFoundError(f"Missing Host resource: {name}")
            shutil.copy2(repo / "LICENSE", folder / "LICENSE-DisplayHDR.txt")
            shutil.copy2(repo / "docs/Portable_Packages.md", folder / "README.md")
            shutil.copy2(repo / "docs/Automation_API.md", folder / "Automation_API.md")
            if role == "Client":
                shutil.copy2(repo / "docs/GUI_Remote.md", folder / "GUI_Remote.md")
                shutil.copy2(repo / "docs/Qt_Notices.md", folder / "Qt_Notices.md")
            remote_doc = (repo / "docs/Remote_API.md").read_text(encoding="utf-8").replace("(Portable_Packages.md)", "(README.md)")
            (folder / "Remote_API.md").write_text(remote_doc, encoding="utf-8")
            manifest = {"role": role, "platform": "Windows x64", "pythonVersion": VERSION,
                        "runtimeSource": RUNTIME_URL, "runtimeArchiveSha256": RUNTIME_SHA256,
                        "files": {str(p.relative_to(folder)).replace("\\", "/"): digest(p)
                                  for p in sorted(folder.rglob("*")) if p.is_file()}}
            if role == "Client":
                manifest["qtVersion"] = QT_VERSION
                manifest["qtWheelSources"] = [{"url": url + name, "sha256": sha} for name, url, sha in QT_WHEELS]
            (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            target = args.output / f"{folder.name}.zip"
            with ZipFile(target, "w", ZIP_DEFLATED) as output:
                for file in sorted(folder.rglob("*")):
                    if file.is_file():
                        output.write(file, file.relative_to(stage))
            packages.append({"file": target.name, "bytes": target.stat().st_size, "sha256": digest(target)})
        (args.output / "SHA256SUMS.txt").write_text("\n".join(f"{p['sha256']}  {p['file']}" for p in packages) + "\n", encoding="ascii")
        print(json.dumps(packages, indent=2))
    finally:
        shutil.rmtree(stage)


if __name__ == "__main__":
    main()
