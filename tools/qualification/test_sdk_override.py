"""Policy tests only: every subprocess is mocked; no local Cargo execution."""

import json
import itertools
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import sdk_override as sdk


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.process = patch.object(sdk.subprocess, "run").start()
        self.addCleanup(patch.stopall)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.evidence = self.root / "evidence"
        self.config = sdk.candidate()
        self.manifest = (
            '[workspace.dependencies]\n'
            'c2pa = { version = "=0.91.0", features = ["pdf"], default-features = false }\n'
        )
        (self.root / "Cargo.toml").write_text(self.manifest)
        (self.root / "Cargo.lock").write_text("original lock\n")
        patch.object(sdk, "ROOT", self.root).start()
        patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "QUALIFICATION_JS_SHA": "a" * 40}).start()

    def resolution(self):
        package = {"name": "c2pa", "version": self.config["version"],
                   "source": sdk.expected_source(self.config)}
        return {"packages": [package]}, {"package": [package, {
            "name": "wasm-bindgen", "version": "0.2.129"
        }]}

    def prepare(self):
        metadata, lock = self.resolution()

        def process(args, **kwargs):
            if args[:2] == ("git", "rev-parse"):
                output = "a" * 40 + "\n"
            elif args[1] == "generate-lockfile":
                text = "".join(
                    "[[package]]\n" + "".join(f'{key} = {json.dumps(value)}\n' for key, value in p.items())
                    for p in lock["package"]
                )
                (self.root / "Cargo.lock").write_text(text)
                output = ""
            elif args[1] == "metadata":
                output = json.dumps(metadata)
            else:
                self.fail(f"Unexpected subprocess {args}")
            return subprocess.CompletedProcess(args, 0, output, "")

        self.process.side_effect = process
        with patch.object(sdk.shutil, "which", return_value="/runner/cargo"):
            sdk.prepare(self.evidence)

    def test_rejects_local_cargo_before_any_subprocess(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaisesRegex(RuntimeError, "only on GitHub"):
                sdk.prepare(self.evidence)
        self.process.assert_not_called()

    def test_configuration_requires_allowlisted_repo_and_exact_sha(self):
        for key, bad in (("repository", "https://github.com/mstattma/c2pa-rs"),
                         ("revision", "main"), ("revision", "A" * 40),
                         ("revision", "a" * 39), ("version", "0.91.0")):
            with self.subTest(key=key, bad=bad):
                path = self.root / "config.json"
                path.write_text(json.dumps({**self.config, key: bad}))
                with self.assertRaises(ValueError):
                    sdk.candidate(path)

    def test_override_preserves_features_and_rejects_already_pinned_source(self):
        result = sdk.override_manifest(self.manifest, self.config)
        dep = tomllib.loads(result)["workspace"]["dependencies"]["c2pa"]
        self.assertEqual(dep["rev"], self.config["revision"])
        self.assertEqual(dep["features"], ["pdf"])
        self.assertFalse(dep["default-features"])
        with self.assertRaises(ValueError):
            sdk.override_manifest(result, self.config)
        self.process.assert_not_called()

    def test_resolution_rejects_registry_wrong_sha_version_and_duplicate(self):
        for key, value in (("source", "registry+https://github.com/rust-lang/crates.io-index"),
                           ("source", sdk.expected_source(self.config)[:-1] + "0"),
                           ("version", "0.91.0")):
            for side in ("metadata", "lock"):
                with self.subTest(key=key, side=side):
                    metadata, lock = self.resolution()
                    target = metadata["packages"] if side == "metadata" else lock["package"]
                    target[0] = {**target[0], key: value}
                    with self.assertRaises(ValueError):
                        sdk.validate_resolution(metadata, lock, self.config)
        metadata, lock = self.resolution()
        metadata["packages"].append(metadata["packages"][0].copy())
        with self.assertRaises(ValueError):
            sdk.validate_resolution(metadata, lock, self.config)

    def test_prepare_snapshots_originals_and_resolves_locked(self):
        self.prepare()
        self.assertEqual((self.evidence / "original-Cargo.toml").read_text(), self.manifest)
        self.assertEqual((self.evidence / "original-Cargo.lock").read_text(), "original lock\n")
        self.assertEqual((self.evidence / "wasm-bindgen-version.txt").read_text(), "0.2.129\n")
        self.assertIn("locked-cargo", (self.evidence / "bin/cargo").read_text())
        args = [call.args[0] for call in self.process.call_args_list]
        self.assertIn(("/runner/cargo", "generate-lockfile"), args)
        self.assertIn(("/runner/cargo", "metadata", "--locked", "--format-version", "1"), args)
        sdk.verify(self.evidence)

    def test_changed_head_rejected(self):
        with patch.dict(os.environ, {"QUALIFICATION_JS_SHA": "b" * 40}):
            with self.assertRaisesRegex(ValueError, "requested JS PR head"):
                self.prepare()
        self.assertEqual((self.root / "Cargo.toml").read_text(), self.manifest)

    def test_wrapper_locks_indirect_nx_and_schema_invocations(self):
        self.prepare()
        with patch.object(sdk, "verify", return_value={"realCargo": "/runner/cargo"}):
            self.process.side_effect = None
            self.process.return_value = subprocess.CompletedProcess([], 0)
            for args in (["build", "--release"], ["--color", "always", "metadata", "--format-version=1"],
                         ["run"], ["check", "--locked"]):
                self.assertEqual(sdk.locked_cargo(self.evidence, args), 0)
                effective = self.process.call_args.args[0]
                self.assertEqual(effective.count("--locked"), 1)
                self.assertEqual(effective[0], "/runner/cargo")
            for args in (["publish"], ["install", "cargo-build"], ["update"],
                         ["metadata", "--manifest-path=other/Cargo.toml"]):
                with self.assertRaises(ValueError):
                    sdk.locked_cargo(self.evidence, args)

    def test_lock_or_manifest_mutation_rejected(self):
        self.prepare()
        for name in ("Cargo.toml", "Cargo.lock"):
            original = (self.root / name).read_bytes()
            (self.root / name).write_bytes(original + b"\n")
            with self.assertRaisesRegex(ValueError, "after lock preparation"):
                sdk.verify(self.evidence)
            (self.root / name).write_bytes(original)

    def test_browser_report_requires_both_browsers_and_all_nine_offsets(self):
        self.evidence.mkdir()
        report = {"success": True, "numPassedTests": 100, "testResults": [{
            "name": "/packages/c2pa-web/src/lib/reader.singleFile.spec.ts",
            "assertionResults": [{"status": "passed"} for _ in range(9)]
        }]}
        for browser in ("chromium", "firefox"):
            (self.evidence / f"{browser}.json").write_text(json.dumps(report))
        sdk.verify_reports(self.evidence)
        for status in ("pending", "skipped", "failed"):
            report["testResults"][0]["assertionResults"][0]["status"] = status
            (self.evidence / "firefox.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "firefox"):
                sdk.verify_reports(self.evidence)


class WorkflowPolicyTests(unittest.TestCase):
    def test_only_the_authorized_fork_branch_replaces_ordinary_main(self):
        root = Path(__file__).resolve().parents[2]
        ordinary = (root / ".github/workflows/ci.yml").read_text()
        qualification = (root / ".github/workflows/fragment-offset-qualification.yml").read_text()
        conditions = [
            "github.repository == 'mstattma/c2pa-js'",
            "github.event_name == 'pull_request'",
            "github.event.pull_request.head.repo.full_name == 'mstattma/c2pa-js'",
            "github.event.pull_request.head.ref == 'feat/upstream-fragment-base-offset'",
            "github.event.pull_request.user.login == 'mstattma'",
            "github.event.pull_request.author_association == 'OWNER'",
        ]
        for condition in conditions:
            self.assertIn(condition, ordinary)
            self.assertIn(condition, qualification)
        guards = [re.search(r"\$\{\{ (.*?) \}\}", text, re.DOTALL)[1]
                  for text in (ordinary, qualification)]
        for values in itertools.product((False, True), repeat=len(conditions)):
            results = []
            for guard in guards:
                for condition, value in zip(conditions, values):
                    guard = guard.replace(condition, str(value))
                guard = guard.replace("&&", " and ").replace("||", " or ").replace("!", "not ")
                results.append(eval(" ".join(guard.split()), {"__builtins__": {}}, {}))
            self.assertEqual(results, [not all(values), all(values)])
        self.assertIn("${{ !(github.repository", ordinary)
        self.assertNotIn("if:", ordinary.split("cargo_fmt:")[1].split("  main:")[0])
        self.assertNotIn("workflow_dispatch", qualification)
        self.assertNotIn("pull_request_target", qualification)
        self.assertNotIn("push:", qualification)
        self.assertNotIn("cache:", qualification)
        self.assertNotIn("continue-on-error", qualification)
        for name in ("Run existing web typecheck (mandatory)",
                     "Run existing utilities typecheck (mandatory)",
                     "Install Chromium and Firefox", "Full web suite including offsets (Chromium)",
                     "Full web suite including offsets (Firefox)"):
            step = qualification.split(f"- name: {name}\n")[1].split("\n      - ")[0]
            self.assertIn("!cancelled() && steps.", step)
        self.assertNotIn("runner.temp", qualification.split("    steps:")[0])
        self.assertIn("persist-credentials: false", qualification)
        self.assertIn("retention-days: 14", qualification)
        for line in qualification.splitlines():
            if "uses:" in line:
                self.assertRegex(line, r"uses: [\w/-]+@[0-9a-f]{40}( |$)")


if __name__ == "__main__":
    unittest.main()
