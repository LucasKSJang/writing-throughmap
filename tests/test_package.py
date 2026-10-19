import json
import unittest

from tests.support import ROOT, repo_files


class PackageTests(unittest.TestCase):
    def test_plugin_manifest(self):
        m = json.loads((ROOT / ".claude-plugin/plugin.json").read_text("utf-8"))
        self.assertEqual(m["name"], "writing-throughmap")
        self.assertEqual(m["version"], "0.1.0")
        self.assertEqual(m["license"], "MIT")
        self.assertEqual(m["author"], {"name": "Lucas Jang"})
        self.assertEqual(m["repository"], "https://github.com/LucasKSJang/writing-throughmap")

    def test_marketplace_points_at_repo_root(self):
        mk = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text("utf-8"))
        self.assertEqual(mk["name"], "writing-throughmap")
        self.assertEqual(mk["owner"], {"name": "Lucas Jang"})
        self.assertEqual([(p["name"], p["source"]) for p in mk["plugins"]],
                         [("writing-throughmap", "./")])

    def test_files_fit_directory_limits(self):
        files = repo_files()
        self.assertLessEqual(len(files), 512)
        images_fonts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".woff", ".woff2", ".ttf", ".otf"}
        for f in files:
            self.assertFalse(f.is_symlink(), f)
            self.assertNotIn(f.suffix.lower(), {".docx", ".pdf", ".zip", ".ico", ".exe", ".dll"}, f)
            self.assertNotIn(f.name, {".DS_Store", "Thumbs.db", "desktop.ini", "package-lock.json",
                                      "npm-shrinkwrap.json", "bun.lock", "bun.lockb"}, f)
            if f.suffix.lower() not in images_fonts:
                self.assertLess(f.stat().st_size, 256 * 1024, f)

    def test_gitattributes_lf_without_forbidden_attributes(self):
        text = (ROOT / ".gitattributes").read_text("utf-8")
        self.assertIn("eol=lf", text)
        for bad in ("export-ignore", "export-subst", "filter"):
            self.assertNotIn(bad, text)

    def test_license_is_mit(self):
        text = (ROOT / "LICENSE").read_text("utf-8")
        self.assertTrue(text.startswith("MIT License"))
        self.assertIn("Copyright (c) 2026 Lucas Jang", text)
