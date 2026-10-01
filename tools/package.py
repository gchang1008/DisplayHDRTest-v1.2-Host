"""Build the self-contained Windows x64 Host ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
from zipfile import ZipFile, ZIP_DEFLATED
VERSION = '3.13.16'
RUNTIME_URL = f'https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip'
RUNTIME_SHA256 = '97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    repo = Path(__file__).resolve().parents[1]
    workspace = repo
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, default=workspace / 'build-output/automation-x64-Release')
    parser.add_argument('--output', type=Path, default=repo / 'dist')
    args = parser.parse_args()
    cache = workspace / 'build-output/package-cache'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f'python-{VERSION}-embed-amd64.zip'
    if not archive.exists():
        urllib.request.urlretrieve(RUNTIME_URL, archive)
    if digest(archive) != RUNTIME_SHA256:
        raise RuntimeError('Embedded Python archive SHA-256 does not match the official release.')
    executable = args.release / 'DisplayHDRComplianceTests.exe'
    if not executable.is_file():
        raise FileNotFoundError(executable)
    args.output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='portable-package-', dir=cache.parent))
    if not stage.resolve().is_relative_to((workspace / 'build-output').resolve()):
        raise RuntimeError('Package stage is outside build-output.')
    try:
        packages = []
        role = 'Host'
        folder = stage / f'DisplayHDR_{role}_x64'
        runtime = folder / 'runtime'
        runtime.mkdir(parents=True)
        with ZipFile(archive) as source:
            source.extractall(runtime)
        (runtime / 'python313._pth').write_text('python313.zip\n.\n..\n', encoding='ascii')
        files = ('displayhdr_api.py', 'displayhdr_server.py', 'displayhdr_supervisor.py', 'StartDisplayHDR.cmd')
        for name in files:
            shutil.copy2(repo / 'tools' / name, folder / name)
        shutil.copy2(executable, folder / executable.name)
        for extension in ('*.cso', '*.png'):
            for resource in args.release.glob(extension):
                shutil.copy2(resource, folder / resource.name)
        required = ('BackgroundNoiseEffect.cso', 'BandedGradientEffect.cso', 'SineSweepEffect.cso', 'ToneSpikeEffect.cso', 'CalibriBoth96Dpi.png', 'OnePixelLinesBW1200x700.png', 'OnePixelLinesRG1200x700.png')
        for name in required:
            if not (folder / name).is_file():
                raise FileNotFoundError(f'Missing Host resource: {name}')
        shutil.copy2(repo / 'LICENSE', folder / 'LICENSE-DisplayHDR.txt')
        shutil.copy2(repo / 'docs/Portable_Packages.md', folder / 'README.md')
        shutil.copy2(repo / 'docs/Automation_API.md', folder / 'Automation_API.md')
        remote_doc = (repo / 'docs/Remote_API.md').read_text(encoding='utf-8').replace('(Portable_Packages.md)', '(README.md)')
        (folder / 'Remote_API.md').write_text(remote_doc, encoding='utf-8')
        manifest = {'role': role, 'platform': 'Windows x64', 'pythonVersion': VERSION, 'runtimeSource': RUNTIME_URL, 'runtimeArchiveSha256': RUNTIME_SHA256, 'files': {str(p.relative_to(folder)).replace('\\', '/'): digest(p) for p in sorted(folder.rglob('*')) if p.is_file()}}
        (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        target = args.output / f'{folder.name}.zip'
        with ZipFile(target, 'w', ZIP_DEFLATED) as output:
            for file in sorted(folder.rglob('*')):
                if file.is_file():
                    output.write(file, file.relative_to(stage))
        packages.append({'file': target.name, 'bytes': target.stat().st_size, 'sha256': digest(target)})
        (args.output / 'SHA256SUMS.txt').write_text('\n'.join((f"{p['sha256']}  {p['file']}" for p in packages)) + '\n', encoding='ascii')
        print(json.dumps(packages, indent=2))
    finally:
        shutil.rmtree(stage)
if __name__ == '__main__':
    main()
