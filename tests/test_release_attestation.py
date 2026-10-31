"""Keyless release workflow contracts; never contacts GitHub or signs."""
import pathlib
import re
import os
import subprocess
import tempfile
import textwrap
import hashlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReleaseAttestation(unittest.TestCase):
    def workflow(self):
        return (ROOT / ".github/workflows/release.yml").read_text()

    def test_native_archives_are_attested_after_verification_and_bundle_uploaded(self):
        workflow = self.workflow()
        build = workflow.split("  build:", 1)[1].split("  plugin:", 1)[0]
        self.assertRegex(build, r"uses: actions/attest@[0-9a-f]{40}")
        self.assertIn("id-token: write", build)
        self.assertIn("attestations: write", build)
        self.assertLess(build.index("Verify archive inventory, preview and isolated installation"),
                        build.index("uses: actions/attest@"))
        self.assertIn("subject-path: dist/wisp-${{ matrix.name }}.tar.gz", build)
        self.assertIn("steps.provenance.outputs.bundle-path", build)
        self.assertIn('"dist/wisp-$BUNDLE_TARGET.tar.gz.sigstore.json"', build)
        self.assertIn("dist/*.sigstore.json", build)

    def test_dispatch_must_execute_on_the_selected_tag_not_a_branch(self):
        block = self.workflow().split(
            "      - name: Validate release tag and derive reproducible metadata\n", 1)[1]
        run = re.search(r"        run: \|\n((?:          .*\n)+)", block).group(1)
        script = textwrap.dedent(run)
        with tempfile.TemporaryDirectory() as td:
            home = pathlib.Path(td)
            git = home / "git"
            git.write_text("#!/bin/sh\ncase \"$1\" in\n"
                           "show) echo 1700000000;;\n"
                           "*) echo " + "a" * 40 + ";;\nesac\n")
            git.chmod(0o755)
            env = dict(os.environ, PATH=str(home), RELEASE_TAG="v1.2.3-rc.1",
                       GITHUB_REF="refs/heads/master", GITHUB_SHA="a" * 40,
                       GITHUB_WORKSPACE=str(home), GITHUB_ENV=str(home / "env"))
            result = subprocess.run(["/bin/bash", "-c", script], env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, "branch dispatch must not attest a tag")
            self.assertFalse((home / "env").exists())
            env["GITHUB_REF"] = "refs/tags/v1.2.3-rc.1"
            result = subprocess.run(["/bin/bash", "-c", script], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_draft_is_published_only_after_downloaded_bundles_verify(self):
        release = self.workflow().split("  release:", 1)[1]
        for name in ("wisp-linux-x86_64.tar.gz.sigstore.json",
                     "wisp-linux-aarch64.tar.gz.sigstore.json"):
            self.assertIn(name, release)
        self.assertIn("gh attestation verify", release)
        for flag in ("--bundle", "--repo", "--cert-identity", "--source-ref",
                     "--source-digest", "--signer-digest", "--deny-self-hosted-runners"):
            self.assertIn(flag, release)
        self.assertLess(release.index("verify_attestations dist"),
                        release.index('gh release create "$RELEASE_TAG"'))
        self.assertLess(release.index('gh release download "$RELEASE_TAG"'),
                        release.index("verify_attestations downloaded"))
        self.assertLess(release.index("verify_attestations downloaded"),
                        release.index('gh release edit "$RELEASE_TAG"'))
        create = release.split('gh release create "$RELEASE_TAG"', 1)[1].split("\n          #", 1)[0]
        self.assertIn("dist/*.sigstore.json", create)

    def test_publication_shell_fails_closed_with_stubbed_gh(self):
        block = self.workflow().split(
            "      - name: Create verified draft release, upload everything, then publish\n", 1)[1]
        script = textwrap.dedent(re.search(
            r"        run: \|\n((?:          .*\n)+)", block).group(1))
        for failure in ("local", "downloaded", "none"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as td:
                home = pathlib.Path(td)
                dist = home / "dist"
                dist.mkdir()
                for target in ("linux-x86_64", "linux-aarch64"):
                    (dist / f"wisp-{target}.tar.gz").write_bytes(b"archive fixture")
                    (dist / f"wisp-{target}.tar.gz.sigstore.json").write_bytes(b"bundle fixture")
                (dist / "wisp-plugin-v1.2.3-rc.1.tar.gz").write_bytes(b"plugin")
                sums = "".join(hashlib.sha256(p.read_bytes()).hexdigest()
                               + "  " + p.name + "\n" for p in sorted(dist.iterdir()))
                (dist / "SHA256SUMS").write_text(sums)
                git = home / "git"
                git.write_text("#!/bin/sh\necho " + "a" * 40 + "\n")
                git.chmod(0o755)
                gh = home / "gh"
                gh.write_text(
                    "#!/bin/sh\nset -eu\necho \"$*\" >> \"$CALL_LOG\"\n"
                    "case \"$1 $2\" in\n"
                    "'attestation verify')\n"
                    " case \"$FAILURE:$3\" in local:dist/*|downloaded:downloaded/*) exit 9;; esac;;\n"
                    "'release view') exit 1;;\n"
                    "'release download') /bin/cp dist/* downloaded/;;\n"
                    "'release create'|'release edit') :;;\n"
                    "*) exit 88;;\nesac\n")
                gh.chmod(0o755)
                env = {"PATH": str(home) + os.pathsep + os.defpath,
                       "RELEASE_TAG": "v1.2.3-rc.1",
                       "GITHUB_REF": "refs/tags/v1.2.3-rc.1",
                       "GITHUB_SHA": "a" * 40,
                       "GITHUB_REPOSITORY": "duketopceo/wisp",
                       "FAILURE": failure, "CALL_LOG": str(home / "calls")}
                result = subprocess.run(["/bin/bash", "-c", script], cwd=home,
                                        env=env, capture_output=True, text=True)
                calls = (home / "calls").read_text()
                if failure == "none":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(calls.count("attestation verify"), 4)
                    self.assertIn("release edit v1.2.3-rc.1 --draft=false --prerelease", calls)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("release edit", calls)
                    self.assertEqual("release create" in calls, failure == "downloaded")
