import os
import tempfile
import unittest
from unittest import mock
from src import confluence2md

# python

from src.confluence2md import (
    PathRel,
    html_to_markdown_via_html2text,
    fetch_and_save,
    init_session,
    download_attachment,
    rewrite_and_download_attachments,
    list_attachments_for_page,
)


class TestConfluence2Md(unittest.TestCase):
    def tearDown(self):
        # Reset module globals that tests may mutate
        confluence2md.SESSION = None
        # Don't remove CONFLUENCE_URL if not set; guard
        if hasattr(confluence2md, "CONFLUENCE_URL"):
            try:
                delattr(confluence2md, "CONFLUENCE_URL")
            except Exception:
                try:
                    del confluence2md.CONFLUENCE_URL  # fallback
                except Exception:
                    pass

    def test_PathRel_returns_relative_path(self):
        # create a temp dir and file
        with tempfile.TemporaryDirectory() as tmp:
            base = tmp
            file_path = os.path.join(tmp, "sub", "file.txt")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write("x")
            rel = PathRel(file_path, base)
            # Should be a relative path referencing the sub/file.txt
            self.assertIn("sub", rel)
            self.assertTrue(rel.endswith("file.txt"))

    def test_PathRel_fallback_to_basename_on_error(self):
        # Pass objects that will cause os.path.relpath to raise
        class BadPath:
            def __fspath__(self):
                raise RuntimeError("boom")

        # Provide a path-like string for path and an object for base_dir to trigger exception
        res = PathRel("/some/path/file.txt", BadPath())
        # fallback returns basename
        self.assertEqual(res, "file.txt")

    def test_html_to_markdown_via_html2text_simple(self):
        html = "<h1>Title</h1><p>Hello <strong>World</strong></p>"
        md = html_to_markdown_via_html2text(html)
        # Basic checks for converted content
        self.assertIn("Title", md)
        self.assertIn("Hello", md)
        self.assertIn("World", md)

    def test_fetch_and_save_without_session_raises(self):
        # Ensure SESSION is None
        confluence2md.SESSION = None
        with self.assertRaises(RuntimeError) as cm:
            fetch_and_save(page_id="123")
        self.assertIn("Credentials not initialized", str(cm.exception))

    def test_init_session_early_validation_errors(self):
        # Missing params should raise ValueError before any network calls
        with self.assertRaises(ValueError):
            init_session("", "", "")
        # Placeholder email should raise
        with self.assertRaises(ValueError):
            init_session("https://your-domain.atlassian.net/wiki", "you@example.com", "api-token")

    def test_download_attachment_no_download_link_returns_none(self):
        # Set minimal globals required
        confluence2md.CONFLUENCE_URL = "https://example.atlassian.net"
        confluence2md.SESSION = mock.Mock()
        # Attachment lacking _links and id/title
        att = {}
        out_dir = tempfile.TemporaryDirectory()
        try:
            result = download_attachment(att, pathlib := mock.Mock(), page_id=None)
            # When out_dir is not a pathlib.Path this will early-return None because no download_link
            self.assertIsNone(result)
        finally:
            out_dir.cleanup()

    def test_rewrite_and_download_attachments_no_attachments_leaves_html(self):
        # Patch list_attachments_for_page to return empty list so no downloads attempted
        html = '<p><img src="/download/attachments/12345/image.png" /></p><p><a href="/download/attachments/12345/doc.pdf">doc</a></p>'
        with mock.patch.object(confluence2md, "list_attachments_for_page", return_value=[]):
            # Use dummy paths for attachments_dir and base_dir
            attachments_dir = tempfile.TemporaryDirectory()
            base_dir = tempfile.TemporaryDirectory()
            try:
                out = rewrite_and_download_attachments(html, page_id="12345", attachments_dir=attachments_dir.name, base_dir=base_dir.name)
                # Since no attachments exist, original src/href should still be present
                self.assertIn('/download/attachments/12345/image.png', out)
                self.assertIn('/download/attachments/12345/doc.pdf', out)
            finally:
                attachments_dir.cleanup()
                base_dir.cleanup()

    def test_list_attachments_for_page_pagination(self):
        # Prepare two fake JSON pages
        page1 = {"results": [{"id": "1", "title": "a"}], "_links": {"next": "/next?page=2"}}
        page2 = {"results": [{"id": "2", "title": "b"}], "_links": {}}

        # Create mock responses with .json() returning page1 then page2
        mock_resp1 = mock.Mock()
        mock_resp1.json.return_value = page1
        mock_resp2 = mock.Mock()
        mock_resp2.json.return_value = page2

        calls = []

        def fake_get(url, params=None, stream=False):
            # return different mocks based on calls count
            calls.append((url, params))
            if len(calls) == 1:
                return mock_resp1
            return mock_resp2

        with mock.patch.object(confluence2md, "_get", side_effect=fake_get):
            # Ensure CONFLUENCE_URL used for joining next links
            confluence2md.CONFLUENCE_URL = "https://example.atlassian.net"
            result = list_attachments_for_page("123")
            # Expect both results combined
            self.assertEqual(len(result), 2)
            ids = {r["id"] for r in result}
            self.assertEqual(ids, {"1", "2"})
            # Ensure _get was called at least twice (pagination)
            self.assertGreaterEqual(len(calls), 2)

    def test_fetch_and_save_success_writes_markdown(self):
        # Setup SESSION to non-None so guard passes
        confluence2md.SESSION = mock.Mock()

        # Fake page returned by get_page_by_id
        fake_page = {
            "id": "42",
            "title": "My Page",
            "body": {"storage": {"value": "<p>Hello world</p>"}},
        }

        # Patch get_page_by_id to avoid network
        with mock.patch.object(confluence2md, "get_page_by_id", return_value=fake_page):
            # Patch rewrite_and_download_attachments to be identity (no download)
            with mock.patch.object(confluence2md, "rewrite_and_download_attachments", return_value="<p>Hello world</p>"):
                # Use temp dir for out
                tmpdir = tempfile.TemporaryDirectory()
                try:
                    info = fetch_and_save(page_id="42", out=tmpdir.name, use_pandoc=False)
                    # Check returned info contains md_path and md_content and attachments_dir None
                    self.assertIn("md_path", info)
                    self.assertIn("md_content", info)
                    self.assertIsNone(info["attachments_dir"])
                    # File exists and contains header and content
                    md_path = info["md_path"]
                    self.assertTrue(os.path.exists(md_path))
                    with open(md_path, "r", encoding="utf-8") as f:
                        contents = f.read()
                    self.assertIn("# My Page", contents)
                    self.assertIn("Hello world", contents)
                finally:
                    tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()