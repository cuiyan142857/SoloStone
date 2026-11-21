#!/usr/bin/env python3
"""Build and run the experimental SoloStone macOS client."""
import argparse
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as xml
import zipfile

sys.dont_write_bytecode = True
import loader_inputs

INSTALLER = Path(__file__).resolve().parent
REPO = INSTALLER.parent
APP = Path("Hearthstone.app")
MANAGED = APP / "Contents/Resources/Data/Managed"
GAME_FILES = ("Data", ".build.info", ".product.db")
BEPINEX_URL = ("https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.5/"
               "BepInEx_macos_universal_5.4.23.5.zip")
BEPINEX_HASH = "01c2ae782eb016dfd6c345a18dbd2dcafffb3d9d318449d6486689f426b4a323"
MONO_INPUTS = INSTALLER / "loader-inputs-mirror-candidate.json"
MONO_MIRROR = ("https://raw.githubusercontent.com/Pik-4/HsMod/551d4423d789c7316303376b616688dafbf05c6c/"
               "HsMod/UnstrippedCorlibUinx/")
STAMP = ".solostone-macos.json"
PLUGIN_FILES = ("SoloStone.Plugin.dll", "SabberStoneCore.dll")
SANDBOX = "/usr/bin/sandbox-exec"


class PreviewError(RuntimeError):
    pass


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inside(path, directory):
    return path == directory or directory in path.parents


def plain_file(path):
    if not path.is_file() or path.resolve() != path or path.stat().st_nlink != 1:
        raise PreviewError(f"Expected an ordinary file in the preview: {path}")
    return path


def game_executable(client):
    with plain_file(client / APP / "Contents/Info.plist").open("rb") as handle:
        name = plistlib.load(handle).get("CFBundleExecutable")
    if not isinstance(name, str) or not name or name in (".", "..") or Path(name).name != name:
        raise PreviewError("Invalid Hearthstone bundle executable name.")
    executable = plain_file(client / APP / "Contents/MacOS" / name)
    if not os.access(executable, os.X_OK):
        raise PreviewError("The Hearthstone bundle executable is not executable.")
    return executable


def copy_client(source, client):
    game_executable(source)
    plain_file(source / MANAGED / "Assembly-CSharp.dll")
    client.mkdir()
    for relative in (APP, *GAME_FILES):
        original = source / relative
        if original.is_symlink():
            raise PreviewError(f"Client input is a symbolic link: {original}")
        if original.exists():
            subprocess.run(["/usr/bin/ditto", str(original), str(client / relative)], check=True)
    for path in client.rglob("*"):
        if path.is_symlink() and not inside(path.resolve(), client):
            raise PreviewError(f"The client contains an external symbolic link: {path.relative_to(client)}")


def stage_loader(client, cache, stock_mono):
    files = []
    archive = loader_inputs.download(BEPINEX_URL, BEPINEX_HASH, cache)
    with zipfile.ZipFile(io.BytesIO(archive)) as loader:
        for member in loader.infolist():
            name = Path(member.filename)
            if name not in (Path("libdoorstop.dylib"), Path("run_bepinex.sh")) and name.parent != Path("BepInEx/core"):
                continue
            target = client / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(loader.read(member))
            files.append(name)
    if stock_mono:
        return files
    inputs = loader_inputs.load(MONO_INPUTS)
    for entry in inputs["files"]:
        if entry["source"] != "unity-mono-corlibs":
            continue
        # The Unix mirror has the same bytes as the Unity 6000.3.11 archive, verified against the existing pins.
        content = loader_inputs.download(MONO_MIRROR + entry["member"], entry["sha256"], cache)
        name = Path(entry["path"])
        target = client / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        files.append(name)
    return files


def prepare(root, source, stock_mono):
    source = source.expanduser().resolve(strict=True)
    if source.name == APP.name:
        source = source.parent
    if inside(root, source) or inside(source, root):
        raise PreviewError("Select the original Hearthstone installation outside the preview.")
    dotnet = os.environ.get("DOTNET") or shutil.which("dotnet")
    if not dotnet:
        raise PreviewError("Install the .NET SDK version in global.json or set DOTNET.")
    with tempfile.TemporaryDirectory(prefix="stage-", dir=root) as work:
        stage = Path(work)
        client = stage / "client"
        copy_client(source, client)
        files = stage_loader(client, root / "cache", stock_mono)
        build = stage / "build"
        subprocess.run([
            dotnet, "build", str(REPO / "plugin/OfflineProbe.csproj"), "-c", "Debug",
            "--output", str(build), "--artifacts-path", str(stage / "artifacts"),
            "-p:MacPreview=true", f"-p:GameReferences={client / MANAGED}",
            f"-p:BepInExReferences={client / 'BepInEx/core'}",
        ], cwd=REPO, check=True)
        for name in PLUGIN_FILES:
            relative = Path("BepInEx/plugins") / name
            (client / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(build / name, client / relative)
            files.append(relative)
        shutil.copyfile(REPO / "client.config", client / "client.config")
        files.extend((Path("client.config"), game_executable(client).relative_to(client),
                      MANAGED / "Assembly-CSharp.dll", MANAGED / "blizzard.bgsclient.dll"))
        hashes = {str(relative): file_hash(plain_file(client / relative)) for relative in files}
        (client / STAMP).write_text(json.dumps({"schema": 1, "files": hashes}, indent=2), encoding="utf-8")
        replace_client(root, client)


def replace_client(root, staged):
    client, previous = root / "client", root / "client.previous"
    if client.exists():
        plain_file(client / STAMP)
        if previous.exists():
            plain_file(previous / STAMP)
            shutil.rmtree(previous)
        client.rename(previous)
    try:
        staged.rename(client)
    except OSError:
        if previous.exists() and not client.exists():
            previous.rename(client)
        raise


def verified_client(root):
    client = root / "client"
    if not client.exists() and (root / "client.previous").exists():
        previous = root / "client.previous"
        plain_file(previous / STAMP)
        previous.rename(client)
    if not client.is_dir():
        raise PreviewError("Run prepare before starting the preview.")
    manifest = json.loads(plain_file(client / STAMP).read_text(encoding="utf-8"))
    files = manifest.get("files")
    executable = game_executable(client)
    required = {str(executable.relative_to(client)), "client.config", "run_bepinex.sh", "libdoorstop.dylib",
                "BepInEx/core/BepInEx.Preloader.dll", str(MANAGED / "Assembly-CSharp.dll"),
                str(MANAGED / "blizzard.bgsclient.dll"), *(f"BepInEx/plugins/{name}" for name in PLUGIN_FILES)}
    if manifest.get("schema") != 1 or not isinstance(files, dict) or not required.issubset(files):
        raise PreviewError("Invalid macOS preview manifest. Run prepare again.")
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or file_hash(plain_file(client / relative)) != expected:
            raise PreviewError(f"Preview file changed: {name}. Run prepare again.")
    for directory in ("core", "plugins", "patchers", "unstripped_corlib"):
        folder = client / "BepInEx" / directory
        if folder.is_symlink():
            raise PreviewError(f"Symbolic link in loader files: {directory}. Run prepare again.")
        for path in folder.rglob("*"):
            if path.is_symlink() or (path.is_file() and str(path.relative_to(client)) not in files):
                raise PreviewError(f"Unknown loader file: {path.relative_to(client)}. Run prepare again.")
    return client, executable, "BepInEx/unstripped_corlib/mscorlib.dll" in files


def preview_env(root):
    home, temp = root / "home", root / "tmp"
    for directory in (home, temp, home / "Library", home / "Library/Preferences", home / "Library/Application Support"):
        private_directory(directory)
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home),
            "CFFIXED_USER_HOME": str(home), "TMPDIR": str(temp), "LANG": "en_US.UTF-8"}


def private_directory(path):
    if path.is_symlink():
        raise PreviewError(f"Symbolic link in preview state: {path}")
    path.mkdir(mode=0o700, exist_ok=True)
    if path.resolve() != path or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022:
        raise PreviewError(f"Preview directory must be owned by you and not writable by other users: {path}")


def sandbox_command(root):
    return [SANDBOX, "-D", f"PREVIEW_ROOT={root}", "-f", str(INSTALLER / "macos-preview.sb")]


def sandbox_probe(allowed, denied):
    allowed.touch(exist_ok=False)
    try:
        denied.touch(exist_ok=False)
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EACCES):
            raise
    else:
        raise PreviewError("The sandbox allowed a write outside the preview.")
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            with socket.socket(family, kind) as probe:
                probe.settimeout(2)
                result = probe.connect_ex((host, 9))
                if result not in (errno.EPERM, errno.EACCES):
                    raise PreviewError(f"The sandbox did not deny {family.name}/{kind.name}: errno {result}.")


def check_sandbox(root):
    with tempfile.TemporaryDirectory(prefix="sandbox-", dir=root) as allowed, tempfile.TemporaryDirectory() as denied:
        # The child must exercise the same kernel policy and writable directory that the game inherits.
        paths = [str(Path(directory).resolve() / "write-test") for directory in (allowed, denied)]
        subprocess.run([*sandbox_command(root), sys.executable, "-E", "-s", "-B", str(Path(__file__).resolve()),
                        "_sandbox_probe", *paths], env=preview_env(root), check=True)


def switch_token(saves, run, started):
    request = plain_file(saves / "profile-switch.xml")
    if request.stat().st_size > 4096 or request.stat().st_mtime < started - 2:
        raise PreviewError("The save-switch request is missing or stale.")
    data = request.read_bytes()
    if b"<!" in data or b"\0" in data:
        raise PreviewError("Invalid save-switch request.")
    doc = xml.fromstring(data)
    token = doc.findtext("Token", "")
    if (doc.tag != "ProfileSwitchRequest" or doc.findtext("Version") != "1"
            or doc.findtext("RunId") != run or not re.fullmatch("[0-9a-f]{32}", token)):
        raise PreviewError("The save-switch request does not match this launch.")
    return token


def stop(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def launch_once(root, client, executable, mono_override, previous, token):
    reports = root / "reports"
    grant, ready, unity_log = (reports / name for name in ("macos-launch.txt", "plugin-loaded.txt", "Unity.log"))
    for path in (grant, ready, unity_log):
        path.unlink(missing_ok=True)
    run = str(uuid.uuid4())
    with grant.open("x", encoding="ascii") as handle:
        handle.write(run)
    args = ["/bin/sh", str(client / "run_bepinex.sh"), str(executable)]
    if mono_override:
        args.extend(("--doorstop-mono-dll-search-path-override", str(client / "BepInEx/unstripped_corlib")))
    args.extend(("-launch", "-uid", "SoloStoneMacPreview", "-hs-macos-root", str(root),
                 "-hs-native-ui-run", run, "-logFile", str(unity_log)))
    if previous:
        args.extend(("-hs-profile-previous-run", previous, "-hs-profile-relaunch-token", token))
    started = time.time()
    try:
        with subprocess.Popen([*sandbox_command(root), *args], cwd=client, env=preview_env(root),
                              stdin=subprocess.DEVNULL, start_new_session=True) as process:
            try:
                deadline = time.monotonic() + 180
                while process.poll() is None and time.monotonic() < deadline:
                    if ready.exists() and plain_file(ready).read_bytes() == run.encode("ascii"):
                        break
                    time.sleep(0.25)
                else:
                    raise PreviewError(f"The plugin did not confirm startup (exit {process.poll()}). See {unity_log} "
                                       f"and {client / 'BepInEx/LogOutput.log'}.")
                grant.unlink()
                print("SoloStone confirmed offline startup. Quit the game to return to the terminal.", flush=True)
                return process.wait(), run, started
            finally:
                stop(process)
    finally:
        grant.unlink(missing_ok=True)


def launch(root):
    client, executable, mono_override = verified_client(root)
    check_sandbox(root)
    previous = token = None
    used = set()
    while True:
        code, run, started = launch_once(root, client, executable, mono_override, previous, token)
        if code != 46:
            if code:
                raise PreviewError(f"Hearthstone exited with status {code}. See the preview logs.")
            return
        token = switch_token(root / "saves", run, started)
        if token in used:
            raise PreviewError("A save-switch token was reused.")
        used.add(token)
        previous = run


@contextmanager
def locked_preview():
    parent = (Path.home() / "Library/Application Support").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / "SoloStone macOS Preview"
    private_directory(root)
    fd = os.open(root / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise PreviewError("Invalid preview lock file.")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PreviewError("Another SoloStone macOS preview operation is active.") from None
        for name in ("reports", "saves", "cache"):
            private_directory(root / name)
        yield root


def main(argv):
    if argv[:1] == ["_sandbox_probe"]:
        sandbox_probe(*(Path(value) for value in argv[1:]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare", help="copy Hearthstone and build the preview plug-in")
    setup.add_argument("client", type=Path, help="original Hearthstone.app or its installation directory")
    setup.add_argument("--stock-mono", action="store_true", help="use the client Mono class libraries for diagnosis")
    commands.add_parser("check", help="validate the macOS sandbox without running Hearthstone")
    commands.add_parser("launch", help="start the prepared copy inside the macOS sandbox")
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or os.geteuid() == 0 or not os.access(SANDBOX, os.X_OK):
        raise PreviewError("The preview requires macOS, sandbox-exec, and a non-root user.")
    with locked_preview() as root:
        if args.command == "prepare":
            prepare(root, args.client, args.stock_mono)
            print(f"Prepared the SoloStone macOS preview in {root}.")
        elif args.command == "check":
            check_sandbox(root)
            print("The preview sandbox denied IPv4, IPv6, and writes outside its directory.")
        else:
            launch(root)


def interrupt(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGHUP, interrupt)
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        sys.exit("SoloStone macOS preview interrupted.")
    except (PreviewError, loader_inputs.Refused, OSError, ValueError, subprocess.SubprocessError, xml.ParseError) as error:
        sys.exit(f"SoloStone macOS preview: {error}")
