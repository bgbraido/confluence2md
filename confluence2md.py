#!/usr/bin/env python3
"""
Usage:
  export CONFLUENCE_URL="https://your-domain.atlassian.net/wiki"
  export CONFLUENCE_USER="you@example.com"
  export CONFLUENCE_API_TOKEN="api-token"
  python scripts/confluence_to_md.py --page-id 12345 --out docs
  OR
  python scripts/confluence_to_md.py --title "Page Title" --space KEY --out docs
Options:
  --pandoc    Use pandoc (must be installed) instead of html2text for HTML->MD conversion.
"""
import os
import sys
import argparse
import requests
from bs4 import BeautifulSoup
import html2text
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import pathlib
import subprocess
import shutil

# previously this file exited at import if env vars were missing.
# Replace that behavior with a lazy session initializer so Streamlit can provide credentials interactively.

# remove module-level AUTH/SESSION initialization; create placeholders
AUTH = None
SESSION = None

def init_session(confluence_url: str, user: str, api_token: str):
	"""
	Initialize global AUTH and SESSION using provided values.
	Call this before any network operations.
	"""
	global CONFLUENCE_URL, CONFLUENCE_USER, CONFLUENCE_API_TOKEN, AUTH, SESSION
	CONFLUENCE_URL = confluence_url
	CONFLUENCE_USER = user
	CONFLUENCE_API_TOKEN = api_token

	if not (CONFLUENCE_URL and CONFLUENCE_USER and CONFLUENCE_API_TOKEN):
		raise ValueError("CONFLUENCE_URL, CONFLUENCE_USER and CONFLUENCE_API_TOKEN are required")

	AUTH = (CONFLUENCE_USER, CONFLUENCE_API_TOKEN)
	SESSION = requests.Session()
	SESSION.auth = AUTH
	SESSION.headers.update({"Accept": "application/json"})

def get_page_by_id(page_id):
    url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}?expand=body.storage,version,ancestors"
    r = SESSION.get(url)
    r.raise_for_status()
    return r.json()

def find_page_by_title(title, space):
    params = {"title": title, "spaceKey": space, "expand": "body.storage"}
    url = f"{CONFLUENCE_URL}/rest/api/content"
    r = SESSION.get(url, params=params)
    r.raise_for_status()
    data = r.json()
    results = data.get("results", [])
    return results[0] if results else None

def list_attachments_for_page(page_id):
    # returns list of attachment dicts
    attachments = []
    start = 0
    limit = 200
    while True:
        url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment"
        params = {"start": start, "limit": limit}
        r = SESSION.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        attachments.extend(data.get("results", []))
        if data.get("size", 0) + data.get("start", 0) >= data.get("limit", 0) + data.get("start", 0) and data.get("_links", {}).get("next"):
            start += limit
            continue
        break
    return attachments

def download_attachment(att, out_dir):
    # att expected to contain _links.download
    download_link = att.get("_links", {}).get("download")
    if not download_link:
        return None
    url = urljoin(CONFLUENCE_URL, download_link)
    filename = att.get("title") or os.path.basename(urlparse(url).path)
    out_path = out_dir / filename
    if out_path.exists():
        return out_path
    r = SESSION.get(url, stream=True)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(4096):
            f.write(chunk)
    return out_path

def rewrite_and_download_attachments(html, page_id, attachments_dir):
    soup = BeautifulSoup(html, "html.parser")

    # map available attachments from listing
    att_list = list_attachments_for_page(page_id)
    att_map = {att.get("title"): att for att in att_list}

    # handle <ri:attachment ri:filename="..."/> (Confluence storage)
    for ri in soup.find_all(lambda tag: tag.name and tag.name.endswith("attachment")):
        filename = ri.attrs.get("ri:filename") or ri.attrs.get("filename")
        if not filename:
            continue
        att = att_map.get(filename)
        if att:
            saved = download_attachment(att, attachments_dir)
            if saved:
                new_img = soup.new_tag("img", src=str(PathRel(saved, attachments_dir)))
                ri.replace_with(new_img)
        else:
            # replace with text fallback
            ri.replace_with(filename)

    # handle <img src="/download/attachments/..." /> and <a href="/download/attachments/...">
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "/download/attachments/" in src:
            filename = os.path.basename(urlparse(src).path)
            # try to find matching attachment by filename
            att = att_map.get(filename)
            if att:
                saved = download_attachment(att, attachments_dir)
                if saved:
                    img['src'] = str(PathRel(saved, attachments_dir))

    for a in soup.find_all("a"):
        href = a.get("href", "")
        if "/download/attachments/" in href:
            filename = os.path.basename(urlparse(href).path)
            att = att_map.get(filename)
            if att:
                saved = download_attachment(att, attachments_dir)
                if saved:
                    a['href'] = str(PathRel(saved, attachments_dir))

    return str(soup)

def PathRel(path, base_dir):
    # return path relative to base_dir (posix style)
    try:
        return os.path.relpath(path, start=base_dir)
    except Exception:
        return os.path.basename(path)

def html_to_markdown_via_html2text(html):
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_images = False
    h.protect_links = True
    return h.handle(html)

def html_to_markdown_via_pandoc(html):
    proc = subprocess.run(["pandoc", "-f", "html", "-t", "gfm"], input=html.encode("utf-8"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"pandoc failed: {proc.stderr.decode()}")
    return proc.stdout.decode("utf-8")

# New: core fetch + save logic refactored into a callable function used by CLI and Streamlit
def fetch_and_save(page_id: str = None, title_arg: str = None, space: str = None, out: str = ".", use_pandoc: bool = False):
	# ensure SESSION initialized from env if not already
	if SESSION is None:
		# try to initialize from already-loaded env vars
		env_url = os.environ.get("CONFLUENCE_URL")
		env_user = os.environ.get("CONFLUENCE_USER")
		env_token = os.environ.get("CONFLUENCE_API_TOKEN")
		if not (env_url and env_user and env_token):
			raise RuntimeError("Credentials not initialized. Call init_session(...) or set CONFLUENCE_* env vars.")
		init_session(env_url, env_user, env_token)

	out_dir = pathlib.Path(out).resolve()
	out_dir.mkdir(parents=True, exist_ok=True)

	if page_id:
		page = get_page_by_id(page_id)
	else:
		page = find_page_by_title(title_arg, space)
		if not page:
			raise RuntimeError(f"Page titled '{title_arg}' not found in space {space}")
		# re-fetch complete page with storage expand
		page = get_page_by_id(page["id"])

	page_id = page["id"]
	title = page.get("title", f"page-{page_id}")
	storage = page.get("body", {}).get("storage", {}).get("value", "")
	if storage is None:
		raise RuntimeError("No storage value found on page.")

	attachments_dir = out_dir / f"{title.replace(' ', '_')}_attachments"
	attachments_dir.mkdir(parents=True, exist_ok=True)

	html_with_local = rewrite_and_download_attachments(storage, page_id, attachments_dir)

	if use_pandoc:
		md = html_to_markdown_via_pandoc(html_with_local)
	else:
		md = html_to_markdown_via_html2text(html_with_local)

	# Save markdown file
	safe_title = "".join(c if c.isalnum() or c in " -_." else "_" for c in title).strip()
	md_path = out_dir / f"{safe_title}.md"
	with open(md_path, "w", encoding="utf-8") as f:
		f.write(f"# {title}\n\n")
		f.write(md)

	return {
		"md_path": str(md_path),
		"attachments_dir": str(attachments_dir) if any(attachments_dir.iterdir()) else None,
		"md_content": md
	}

def main():
	# CLI path: use environment variables (loaded earlier) or require them now
	parser = argparse.ArgumentParser(description="Fetch a Confluence page and convert to Markdown.")
	parser.add_argument("--page-id", type=str, help="Confluence page ID")
	parser.add_argument("--title", type=str, help="Confluence page title (needs --space)")
	parser.add_argument("--space", type=str, help="Space key (required when using --title)")
	parser.add_argument("--out", type=str, default=".", help="Output directory")
	parser.add_argument("--pandoc", action="store_true", help="Use pandoc for HTML->MD conversion")
	args = parser.parse_args()

	if not args.page_id and not args.title:
		parser.error("Provide --page-id or --title with --space")
	if args.title and not args.space:
		parser.error("--space is required when using --title")

	# initialize session from env (fail early for CLI)
	if SESSION is None:
		env_url = os.environ.get("CONFLUENCE_URL")
		env_user = os.environ.get("CONFLUENCE_USER")
		env_token = os.environ.get("CONFLUENCE_API_TOKEN")
		if not (env_url and env_user and env_token):
			print("ERROR: set CONFLUENCE_URL, CONFLUENCE_USER and CONFLUENCE_API_TOKEN environment variables")
			sys.exit(1)
		init_session(env_url, env_user, env_token)

	try:
		info = fetch_and_save(page_id=args.page_id, title_arg=args.title, space=args.space, out=args.out, use_pandoc=args.pandoc)
	except Exception as e:
		print("Error:", e)
		sys.exit(2)

	print(f"Saved: {info['md_path']}")
	if info["attachments_dir"]:
		print(f"Attachments saved under: {info['attachments_dir']}")

# New: Streamlit UI
def run_streamlit():
	try:
		import streamlit as st
	except Exception:
		raise

	st.title("Confluence -> Markdown")

	# credentials (can override .env)
	col1, col2 = st.columns(2)
	with col1:
		confluence_url = st.text_input("CONFLUENCE_URL", value=os.environ.get("CONFLUENCE_URL", ""))
		space = st.text_input("Space key (if using title)", value="")
	with col2:
		confluence_user = st.text_input("CONFLUENCE_USER", value=os.environ.get("CONFLUENCE_USER", ""))
		confluence_token = st.text_input("CONFLUENCE_API_TOKEN", value=os.environ.get("CONFLUENCE_API_TOKEN", ""), type="password")

	st.markdown("### Page selection")
	page_id = st.text_input("Page ID (leave empty to use Title + Space)", value="")
	title_arg = st.text_input("Page Title (used if Page ID empty)", value="")

	out_dir = st.text_input("Output directory", value=".")
	use_pandoc = st.checkbox("Use pandoc for HTML->MD conversion", value=False)

	if st.button("Fetch"):
		# initialize session with provided values (fall back to env if empty)
		url = confluence_url or os.environ.get("CONFLUENCE_URL")
		user = confluence_user or os.environ.get("CONFLUENCE_USER")
		token = confluence_token or os.environ.get("CONFLUENCE_API_TOKEN")
		try:
			init_session(url, user, token)
		except Exception as e:
			st.error(f"Credentials error: {e}")
			return

		with st.spinner("Fetching..."):
			try:
				info = fetch_and_save(page_id=page_id or None, title_arg=title_arg or None, space=space or None, out=out_dir, use_pandoc=use_pandoc)
			except Exception as e:
				st.error(f"Error: {e}")
				return

		st.success(f"Saved: {info['md_path']}")
		if info["attachments_dir"]:
			st.info(f"Attachments saved under: {info['attachments_dir']}")
		# show content and let user download
		st.download_button("Download Markdown", data=info["md_content"].encode("utf-8"), file_name=os.path.basename(info["md_path"]), mime="text/markdown")

# Run Streamlit when available, otherwise fall back to CLI main
try:
	import streamlit  # type: ignore
	# When executed by `streamlit run`, this module is run and streamlit is available;
	# run the UI (do not run CLI main).
	run_streamlit()
except Exception:
	# If streamlit not installed or something failed importing it, use CLI behavior.
	if __name__ == "__main__":
		main()