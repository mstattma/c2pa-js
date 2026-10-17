"""Runner-only SDK qualification override; never changes the committed dependency pin."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".github/qualification/fragment-offset-sdk.json"
ALLOWED_REPOSITORIES = {"https://github.com/castlabs/c2pa-rs"}


def candidate(path=CONFIG):
    value = json.loads(path.read_text())
    if set(value) != {"repository", "revision", "version"}:
        raise ValueError("Unexpected SDK configuration fields")
    if value["repository"] not in ALLOWED_REPOSITORIES:
        raise ValueError("SDK repository is not allowlisted")
    if not re.fullmatch(r"[0-9a-f]{40}", value["revision"]):
        raise ValueError("SDK revision must be an exact lowercase 40-hex SHA")
    if value["version"] != "0.92.0-dev":
        raise ValueError("Unexpected SDK version")
    return value


def require_runner():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Cargo qualification is allowed only on GitHub Actions")


def run(*args):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    result.check_returncode()
    return result.stdout


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def expected_source(sdk):
    return f"git+{sdk['repository']}?rev={sdk['revision']}#{sdk['revision']}"


def validate_resolution(metadata, lock, sdk):
    for packages in (metadata["packages"], lock["package"]):
        matches = [p for p in packages if p["name"] == "c2pa"]
        if len(matches) != 1 or (
            matches[0]["version"] != sdk["version"]
            or matches[0].get("source") != expected_source(sdk)
        ):
            raise ValueError("c2pa must resolve only to the exact candidate git SHA/version")
    versions = {p["version"] for p in lock["package"] if p["name"] == "wasm-bindgen"}
    if len(versions) != 1:
        raise ValueError("Expected exactly one resolved wasm-bindgen version")
    return versions.pop()


def override_manifest(original, sdk):
    manifest = tomllib.loads(original)
    dependency = manifest["workspace"]["dependencies"]["c2pa"]
    if dependency.get("version") != "=0.91.0" or any(
        key in dependency for key in ("git", "rev", "path")
    ):
        raise ValueError("Qualification must start from the stock registry pin")
    # A [patch] cannot replace =0.91.0 with 0.92.0-dev. Replace only its source.
    effective, count = re.subn(
        r'(c2pa\s*=\s*\{\s*)version\s*=\s*"=0\.91\.0"',
        lambda match: match[1] + f'git = "{sdk["repository"]}", rev = "{sdk["revision"]}"',
        original,
    )
    if count != 1:
        raise ValueError("Expected one workspace c2pa dependency")
    result = tomllib.loads(effective)["workspace"]["dependencies"]["c2pa"]
    if result != {
        **{k: v for k, v in dependency.items() if k != "version"},
        "git": sdk["repository"],
        "rev": sdk["revision"],
    }:
        raise ValueError("Override changed dependency features")
    return effective


def prepare(evidence):
    require_runner()
    sdk = candidate()
    evidence.mkdir(parents=True, exist_ok=False)
    for name in ("Cargo.toml", "Cargo.lock"):
        shutil.copyfile(ROOT / name, evidence / f"original-{name}")
    head = run("git", "rev-parse", "HEAD").strip()
    if head != os.environ["QUALIFICATION_JS_SHA"]:
        raise ValueError("Checkout is not the requested JS PR head")
    write_json(evidence / "source.json", {"jsHead": head, "sdk": sdk})
    shutil.copyfile(CONFIG, evidence / "sdk-config.json")
    manifest = ROOT / "Cargo.toml"
    manifest.write_text(override_manifest(manifest.read_text(), sdk))
    shutil.copyfile(manifest, evidence / "effective-Cargo.toml")
    cargo = shutil.which("cargo")
    if not cargo:
        raise RuntimeError("Cargo is not installed on the runner")
    run(cargo, "generate-lockfile")
    metadata_text = run(cargo, "metadata", "--locked", "--format-version", "1")
    (evidence / "cargo-metadata.json").write_text(metadata_text)
    lock = tomllib.loads((ROOT / "Cargo.lock").read_text())
    version = validate_resolution(json.loads(metadata_text), lock, sdk)
    shutil.copyfile(ROOT / "Cargo.lock", evidence / "effective-Cargo.lock")
    write_json(evidence / "effective-override.json", {
        "sdk": sdk,
        "jsHead": head,
        "manifestSha256": digest(manifest),
        "lockSha256": digest(ROOT / "Cargo.lock"),
        "wasmBindgenVersion": version,
        "realCargo": cargo,
    })
    (evidence / "wasm-bindgen-version.txt").write_text(version + "\n")
    # Nx and schema generation inherit this wrapper through PATH. Normal builds do not.
    wrapper = evidence / "bin/cargo"
    wrapper.parent.mkdir()
    wrapper.write_text(
        "#!/bin/sh\nexec " + shlex.join([
            sys.executable, str(Path(__file__).resolve()), "locked-cargo", str(evidence)
        ]) + ' "$@"\n'
    )
    wrapper.chmod(0o755)


def verify(evidence):
    require_runner()
    state = json.loads((evidence / "effective-override.json").read_text())
    for name, key in (("Cargo.toml", "manifestSha256"), ("Cargo.lock", "lockSha256")):
        if digest(ROOT / name) != state[key]:
            raise ValueError(f"Qualification changed {name} after lock preparation")
    if run("git", "rev-parse", "HEAD").strip() != state["jsHead"]:
        raise ValueError("JS HEAD changed during qualification")
    return state


def locked_cargo(evidence, args):
    state = verify(evidence)
    # Support global options emitted by Nx, but no installs, updates or publishing.
    commands = {"build", "run", "metadata", "check", "clippy", "test", "tree", "fetch"}
    if not any(arg in commands for arg in args) or any(
        arg in {"update", "generate-lockfile", "install", "publish", "--manifest-path"}
        or arg.startswith("--manifest-path=") for arg in args
    ):
        raise ValueError(f"Unexpected qualification Cargo invocation: {args}")
    if "--locked" not in args:
        args = [*args, "--locked"]
    with (evidence / "cargo-calls.jsonl").open("a") as log:
        log.write(json.dumps(args) + "\n")
    result = subprocess.run([state["realCargo"], *args], cwd=Path.cwd())
    verify(evidence)
    return result.returncode


def verify_reports(evidence):
    results = {}
    for browser in ("chromium", "firefox"):
        report = json.loads((evidence / f"{browser}.json").read_text())
        offset = [
            assertion
            for suite in report["testResults"]
            if suite["name"].endswith("/reader.singleFile.spec.ts")
            for assertion in suite["assertionResults"]
        ]
        if not report["success"] or len(offset) != 9 or any(
            assertion["status"] != "passed" for assertion in offset
        ):
            raise ValueError(f"{browser}: full suite/9 non-skipped offset tests required")
        results[browser] = {"offsetPassed": len(offset), "totalPassed": report["numPassedTests"]}
    write_json(evidence / "browser-summary.json", results)


if __name__ == "__main__":
    command, directory, *arguments = sys.argv[1:]
    evidence = Path(directory).resolve()
    if command == "prepare":
        prepare(evidence)
    elif command == "verify":
        verify(evidence)
    elif command == "locked-cargo":
        sys.exit(locked_cargo(evidence, arguments))
    elif command == "reports":
        verify_reports(evidence)
    else:
        raise ValueError(f"Unknown command: {command}")
