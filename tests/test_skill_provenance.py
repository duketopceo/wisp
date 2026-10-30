"""Provenance gate: no non-MIT corpus text may appear in wisp artifacts.

Extracts 12-word sequences from non-MIT files in a locally held
third-party skill corpus (outside the repo, research-only) and fails
if any appear in shipped/tracked artifacts. Skips when the corpus
isn't on this machine — the gate only runs where the reference corpus
exists.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = (pathlib.Path.home()
          / ".local/share/wisp/reference/skill-corpus")

# Files the corpus's own ATTRIBUTION marks MIT (or whose bundled
# LICENSE.txt is MIT) — allowed adaptation sources, skipped by the gate.
MIT_LOOSE = {
    "airtable.md", "apple-notes.md", "apple-reminders.md", "blender.md",
    "claude-code.md", "claude-design.md", "codex.md", "excalidraw.md",
    "findmy.md", "github-auth.md", "github-code-review.md",
    "github-issues.md", "github-pr-workflow.md",
    "github-repo-management.md", "google-workspace.md", "imessage.md",
    "linear.md", "maps.md", "notion.md", "obsidian.md",
    "ocr-and-documents.md", "polymarket.md", "spotify.md",
}
MIT_BUNDLED = {"vercel-deploy"}

# Non-skill corpus docs also excluded from the gate input set is wrong —
# they ARE gate inputs (proprietary). Everything not in the MIT sets is
# a gate input.

NGRAM = 12
WORD = re.compile(r"[a-z0-9']+")

# Repo artifacts checked for leaked sequences.
TARGETS = [
    ROOT / "wisp" / "skills_seed",
    ROOT / "tests" / "fixtures" / "skills",
    ROOT / "scripts",
    ROOT / "docs" / "research" / "app-skill-format.md",
    ROOT / "docs" / "research" / "skill-corpus-sources.md",
]


def _norm_words(path: pathlib.Path) -> list[str]:
    return WORD.findall(path.read_text(errors="replace").lower())


def _gate_inputs() -> list[pathlib.Path]:
    files = []
    for f in (CORPUS / "loose").glob("*.md"):
        if f.name not in MIT_LOOSE:
            files.append(f)
    for f in (CORPUS / "integration").glob("*/SKILL.md"):
        files.append(f)
    for d in (CORPUS / "bundled").iterdir():
        if d.is_dir() and d.name not in MIT_BUNDLED:
            files.extend(d.rglob("*.md"))
    return files


def _ngrams(path: pathlib.Path) -> set[str]:
    w = _norm_words(path)
    return {" ".join(w[i:i + NGRAM]) for i in range(len(w) - NGRAM + 1)}


def _target_texts() -> dict[pathlib.Path, str]:
    out = {}
    for t in TARGETS:
        paths = [t] if t.is_file() else sorted(t.rglob("*.md")) + sorted(
            t.rglob("*.py"))
        for p in paths:
            out[p] = " ".join(_norm_words(p))
    return out


@unittest.skipUnless(CORPUS.exists(), "reference corpus not present")
class ProvenanceGateTest(unittest.TestCase):
    def test_no_nonmit_corpus_text_in_artifacts(self):
        targets = _target_texts()
        hits = []
        for src in _gate_inputs():
            for gram in _ngrams(src):
                for tgt, text in targets.items():
                    if gram in text:
                        hits.append(f"{src.name} -> {tgt.relative_to(ROOT)}")
        self.assertEqual(hits, [], "corpus text leaked into artifacts")


if __name__ == "__main__":
    unittest.main()
