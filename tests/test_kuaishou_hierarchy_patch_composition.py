from pathlib import Path
import tempfile
import unittest

from scripts.patch_kuaishou_comment_hierarchy import MARKER, patch_client


class KuaishouHierarchyPatchCompositionTests(unittest.TestCase):
    def _client_path(self, root: Path) -> Path:
        path = root / "media_platform" / "kuaishou" / "client.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def test_region_enrichment_between_subcomments_and_callback_is_supported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._client_path(root)
            path.write_text(
                "async def f(comments_res, callback, photo_id, root_comment_id):\n"
                "    sub_comments = comments_res.get('subCommentsV2', [])\n"
                "    _ks_sub_region_count = _ks_enrich_comment_regions(comments_res, sub_comments)\n"
                "    if sub_comments and _ks_sub_region_count == 0:\n"
                "        _ks_comment_region_debug(comments_res, sub_comments, 'sub')\n"
                "    if callback and sub_comments:\n"
                "        await callback(photo_id, sub_comments)\n",
                encoding="utf-8",
            )
            # Match the real MediaCrawler indentation/quote style used by the patch.
            text = path.read_text(encoding="utf-8")
            text = text.replace("    sub_comments", "                sub_comments")
            text = text.replace("    _ks_sub_region_count", "                _ks_sub_region_count")
            text = text.replace("    if sub_comments", "                if sub_comments")
            text = text.replace("        _ks_comment_region_debug", "                    _ks_comment_region_debug")
            text = text.replace("    if callback", "                if callback")
            text = text.replace("        await callback", "                    await callback")
            text = text.replace("'subCommentsV2'", '"subCommentsV2"')
            path.write_text("async def f(comments_res, callback, photo_id, root_comment_id):\n" + "\n".join(text.splitlines()[1:]) + "\n", encoding="utf-8")

            patch_client(root)
            patched = path.read_text(encoding="utf-8")
            self.assertIn('sub_comment["parent_comment_id"] = str(root_comment_id)', patched)
            self.assertIn('sub_comment["root_comment_id"] = str(root_comment_id)', patched)
            self.assertIn(MARKER, patched)
            self.assertIn("_ks_sub_region_count = _ks_enrich_comment_regions", patched)

    def test_already_tagged_client_is_idempotent_even_with_region_code(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._client_path(root)
            path.write_text(
                "async def f(comments_res, callback, photo_id, root_comment_id):\n"
                "                sub_comments = comments_res.get(\"subCommentsV2\", [])\n"
                "                _ks_sub_region_count = _ks_enrich_comment_regions(comments_res, sub_comments)\n"
                "                for sub_comment in sub_comments:\n"
                "                    if isinstance(sub_comment, dict):\n"
                "                        sub_comment[\"parent_comment_id\"] = str(root_comment_id)\n"
                "                        sub_comment[\"root_comment_id\"] = str(root_comment_id)\n"
                "                if callback and sub_comments:\n"
                "                    await callback(photo_id, sub_comments)\n",
                encoding="utf-8",
            )
            patch_client(root)
            once = path.read_text(encoding="utf-8")
            patch_client(root)
            twice = path.read_text(encoding="utf-8")
            self.assertEqual(once, twice)
            self.assertEqual(twice.count('sub_comment["parent_comment_id"] = str(root_comment_id)'), 1)
            self.assertIn(MARKER, twice)


if __name__ == "__main__":
    unittest.main()
