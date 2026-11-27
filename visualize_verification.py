#!/usr/bin/env python3
"""Launch the HARP Shiny apps for results stored by tactusharpverif."""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        try:
            import toml as tomllib
        except ModuleNotFoundError:
            tomllib = None


DEFAULT_DYNAMIC_PORT = 9999
DEFAULT_STATIC_PORT = 9998
STARTUP_TIMEOUT = 60
PLUGIN_CONFIG = Path(__file__).resolve().with_name("tactusharpverif_plugin.toml")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Launch the HARP RDS and PNG visualization apps on ATOS."
    )
    parser.add_argument(
        "--verif-home",
        help="Verification output root (overrides $VERIF_HOME and plugin TOML).",
    )
    parser.add_argument(
        "--harpscripts-home",
        help="HARP scripts root (overrides $HARPSCRIPTS_HOME and plugin TOML).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PLUGIN_CONFIG,
        help=f"Plugin TOML file (default: {PLUGIN_CONFIG}).",
    )
    parser.add_argument(
        "--dynamic-port",
        type=int,
        default=DEFAULT_DYNAMIC_PORT,
        help=f"Port for the interactive RDS app (default: {DEFAULT_DYNAMIC_PORT}).",
    )
    parser.add_argument(
        "--static-port",
        type=int,
        default=DEFAULT_STATIC_PORT,
        help=f"Port for the PNG app (default: {DEFAULT_STATIC_PORT}).",
    )
    return parser.parse_args()


def fail(message):
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def configured_paths(args):
    """Resolve paths in CLI, environment, plugin TOML precedence order."""
    verif_home = args.verif_home or os.environ.get("VERIF_HOME")
    harpscripts_home = args.harpscripts_home or os.environ.get("HARPSCRIPTS_HOME")
    if verif_home and harpscripts_home:
        return verif_home, harpscripts_home
    if tomllib is None:
        fail(
            "reading plugin TOML requires Python 3.11+ or the 'tomli'/'toml' "
            "package; set both VERIF_HOME and HARPSCRIPTS_HOME to bypass TOML"
        )

    config_path = args.config.expanduser().resolve()
    try:
        config_contents = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        fail(f"cannot read plugin TOML {config_path}: {error}")
    try:
        config = tomllib.loads(config_contents)
    except ValueError as error:
        fail(f"invalid plugin TOML {config_path}: {error}")

    env_config = (
        config.get("submission", {})
        .get("tactusharpverif_group", {})
        .get("ENV", {})
    )
    if not isinstance(env_config, dict):
        fail(
            "plugin TOML setting [submission.tactusharpverif_group.ENV] "
            "must be a table"
        )
    verif_home = verif_home or env_config.get("VERIF_HOME")
    harpscripts_home = harpscripts_home or env_config.get("HARPSCRIPTS_HOME")
    if verif_home is not None and not isinstance(verif_home, str):
        fail("VERIF_HOME in the plugin TOML must be a string path")
    if harpscripts_home is not None and not isinstance(harpscripts_home, str):
        fail("HARPSCRIPTS_HOME in the plugin TOML must be a string path")
    if not verif_home:
        fail(
            "set VERIF_HOME, pass --verif-home, or configure "
            "VERIF_HOME in the plugin TOML"
        )
    if not harpscripts_home:
        fail(
            "set HARPSCRIPTS_HOME, pass --harpscripts-home, or configure "
            "HARPSCRIPTS_HOME in the plugin TOML"
        )
    return verif_home, harpscripts_home


def available_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def check_port(port, option):
    if not 1 <= port <= 65535:
        fail(f"{option} must be between 1 and 65535")
    if not available_port(port):
        fail(f"port {port} is already in use; choose another value for {option}")


def stop_processes(processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def wait_until_ready(apps):
    deadline = time.monotonic() + STARTUP_TIMEOUT
    ready = set()
    while time.monotonic() < deadline:
        for name, process, port, log_path in apps:
            if name in ready:
                continue
            if process.poll() is not None:
                fail(
                    f"{name} exited during startup; see its log: {log_path}"
                )
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.25)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    ready.add(name)
        if len(ready) == len(apps):
            return
        time.sleep(0.25)
    fail(
        "timed out waiting for the Shiny apps to start; check logs: "
        + ", ".join(str(app[3]) for app in apps)
    )


def main():
    args = parse_args()
    configured_verif_home, configured_harpscripts_home = configured_paths(args)
    verif_home = Path(configured_verif_home).expanduser().resolve()
    harpscripts_home = Path(configured_harpscripts_home).expanduser().resolve()
    if not verif_home.is_dir():
        fail(f"VERIF_HOME is not a directory: {verif_home}")
    if not harpscripts_home.is_dir():
        fail(f"HARPSCRIPTS_HOME is not a directory: {harpscripts_home}")
    rscript = shutil.which("Rscript")
    if rscript is None:
        fail("Rscript was not found on PATH; load the configured HARP R environment first")

    visualization_dir = harpscripts_home / "visualization"
    dynamic_launcher = visualization_dir / "launch_dynamicapp_atos.R"
    static_launcher = visualization_dir / "launch_visapp_atos.R"
    for launcher in (dynamic_launcher, static_launcher):
        if not launcher.is_file():
            fail(f"HARP visualization launcher not found: {launcher}")

    if args.dynamic_port == args.static_port:
        fail("--dynamic-port and --static-port must be different")
    check_port(args.dynamic_port, "--dynamic-port")
    check_port(args.static_port, "--static-port")

    logs = (verif_home / "dynamicapp.log", verif_home / "visapp.log")
    commands = (
        (
            "Interactive RDS app",
            [
                rscript,
                str(dynamic_launcher),
                str(verif_home),
                str(args.dynamic_port),
            ],
            args.dynamic_port,
            logs[0],
        ),
        (
            "PNG visualization app",
            [
                rscript,
                str(static_launcher),
                "-img_dir",
                str(verif_home),
                "-port",
                str(args.static_port),
            ],
            args.static_port,
            logs[1],
        ),
    )

    processes = []
    apps = []
    try:
        for name, command, port, log_path in commands:
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=harpscripts_home,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            processes.append(process)
            apps.append((name, process, port, log_path))
        wait_until_ready(apps)
    except (OSError, SystemExit, KeyboardInterrupt):
        stop_processes(processes)
        raise

    print(f"Visualization apps are running from {verif_home}.")
    host = os.environ.get("HOST", "").strip() or "<ATOS_HOST>"
    print("To view both apps in Firefox:")
    print("1. Open a new terminal on the machine where Firefox will run.")
    print(
        "2. Set up SSH port forwarding with:\n"
        f"   ssh -L {args.dynamic_port}:localhost:{args.dynamic_port} "
        f"-L {args.static_port}:localhost:{args.static_port} {host}"
    )
    if host == "<ATOS_HOST>":
        print("   Replace <ATOS_HOST> with the ATOS host running these apps.")
    print("3. Open these URLs in Firefox:")
    print(f"   Interactive RDS results: http://127.0.0.1:{args.dynamic_port}/")
    print(f"   PNG figures:             http://127.0.0.1:{args.static_port}/")
    print("Keep this ATOS session available while using the apps.")
    print(f"App process IDs: {processes[0].pid} (RDS), {processes[1].pid} (PNG)")
    print(f"App logs: {logs[0]} and {logs[1]}")


if __name__ == "__main__":
    main()
