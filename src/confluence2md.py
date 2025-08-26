#!/usr/bin/env python3
"""
Usage:
  Streamlit UI:
    streamlit run src/confluence2md.py

  Programmatic:
    from confluence2md import init_session, fetch_and_save
    init_session("https://my-site.atlassian.net/wiki", "me@example.com", "<api-token>")
    fetch_and_save(page_id="12345", out="docs")
Options:
  --pandoc    Use pandoc (must be installed) instead of html2text for HTML->MD conversion.
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import html2text
import requests
from bs4 import BeautifulSoup

# remove module-level AUTH/SESSION initialization; create placeholders
AUTH = None
SESSION = None
__all__ = ["init_session", "fetch_and_save", "get_page_by_id", "find_page_by_title"]

# Normalize site base and compute API v1 base.
def _wiki_base() -> str:
    # Ensure trailing /wiki once (Confluence Cloud uses this prefix for REST/UI)
    base = CONFLUENCE_URL.rstrip("/")
    return base if base.endswith("/wiki") else base + "/wiki"

def _api_v1_base() -> str:
    return _wiki_base() + "/rest/api"

def _get(url: str, *, params=None, stream: bool = False):
    r = SESSION.get(url, params=params, stream=stream)
    if r.status_code in (401, 403):
        # Enrich error with a concise hint.
        hint = (
            "Unauthorized. Verify email + API token, and that the token belongs to this site. "
            "Also ensure the base URL points to your cloud site (e.g., https://<site>.atlassian.net/wiki)."
        )
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            raise requests.HTTPError(f"{e} — {hint}") from None
    r.raise_for_status()
    return r

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
        raise ValueError(
            "CONFLUENCE_URL, CONFLUENCE_USER and CONFLUENCE_API_TOKEN are required"
        )

    # Guard against placeholders and common mistakes
    if "your-domain.atlassian.net" in CONFLUENCE_URL or CONFLUENCE_USER == "you@example.com" or CONFLUENCE_API_TOKEN in ("api-token", "", None):
        raise ValueError(
            "Replace placeholders with your real Confluence Cloud site URL, email, and API token."
        )
    if "@" not in CONFLUENCE_USER:
        raise ValueError("CONFLUENCE_USER must be your Atlassian account email address.")
    if not CONFLUENCE_URL.startswith("http"):
        raise ValueError("CONFLUENCE_URL must start with http(s) and point to your site (e.g., https://<site>.atlassian.net/wiki).")

    AUTH = (CONFLUENCE_USER, CONFLUENCE_API_TOKEN)
    SESSION = requests.Session()
    SESSION.auth = AUTH
    SESSION.headers.update({"Accept": "application/json"})

    # Probe credentials and site; raise on failure with helpful message
    _get(_api_v1_base() + "/user/current")


def get_page_by_id(page_id):
    # Use v1 API
    pid = str(page_id).strip()
    url = f"{_api_v1_base()}/content/{pid}"
    params = {"expand": "body.storage,version,ancestors"}
    r = _get(url, params=params)
    return r.json()


def _get_space_id_by_key(space_key: str) -> str:
    # v1: GET /rest/api/space/{spaceKey}
    url = f"{_api_v1_base()}/space/{space_key}"
    try:
        r = _get(url)
        data = r.json()
        sid = data.get("id")
        if sid is not None:
            return str(sid)
    except Exception:
        pass
    raise RuntimeError(f"Space '{space_key}' not found or no ID available.")


def find_page_by_title(title, space):
    # Use v1 API
    url = f"{_api_v1_base()}/content"
    params = {
        "title": title,
        "spaceKey": space,
        "expand": "body.storage,version,ancestors",
        "limit": 1
    }
    r = _get(url, params=params)
    data = r.json()
    results = data.get("results", [])
    return results[0] if results else None


def list_attachments_for_page(page_id):
    # v1: GET /rest/api/content/{id}/child/attachment with proper expansion
    attachments = []
    url = f"{_api_v1_base()}/content/{page_id}/child/attachment"
    params = {"limit": 200, "expand": "download"}
    
    while True:
        r = _get(url, params=params)
        data = r.json()
        results = data.get("results", [])
        attachments.extend(results)
        
        # Check for next page using v1 API pagination
        links = data.get("_links", {})
        next_link = links.get("next")
        if not next_link:
            break
        
        # Follow absolute or relative next link
        url = urljoin(CONFLUENCE_URL, next_link)
        params = None
    
    return attachments


def download_attachment(att, out_dir, page_id=None):
    # v1 API attachment structure - try multiple ways to get download URL
    download_link = None
    links = att.get("_links", {})
    
    # Try different possible download link fields
    if "download" in links:
        download_link = links["download"]
    elif "downloadUrl" in links:
        download_link = links["downloadUrl"]
    else:
        # Construct download URL manually using attachment ID and page ID
        att_id = att.get("id")
        if att_id and page_id:
            download_link = f"/download/attachments/{page_id}/{att.get('title', '')}"
        elif att_id:
            # Try with just attachment ID
            download_link = f"/download/attachments/{att_id}"
    
    if not download_link:
        print(f"Warning: No download link found for attachment {att.get('title', 'unknown')}")
        print(f"Attachment data: {att}")
        return None
    
    # Ensure we have a full URL
    if download_link.startswith("/"):
        url = urljoin(CONFLUENCE_URL, download_link)
    else:
        url = download_link
    
    # Get filename from attachment title, fallback to URL parsing
    filename = att.get("title")
    if not filename:
        # Extract filename from URL, handle URL encoding
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        if filename:
            filename = unquote(filename)
        else:
            filename = f"attachment_{att.get('id', 'unknown')}"
    
    # Don't over-sanitize filename - preserve extensions
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_. ")
    filename = "".join(c if c in safe_chars else "_" for c in filename).strip()
    if not filename or filename == ".":
        filename = f"attachment_{att.get('id', 'unknown')}"
    
    out_path = out_dir / filename
    
    if out_path.exists():
        print(f"Attachment already exists: {filename}")
        return out_path
    
    try:
        print(f"Downloading attachment: {filename} from {url}")
        r = _get(url, stream=True)
        
        # Check if we got HTML instead of the file (common with auth issues)
        content_type = r.headers.get('content-type', '').lower()
        if 'text/html' in content_type:
            print(f"Warning: Got HTML response instead of file for {filename}")
            print(f"Response headers: {dict(r.headers)}")
            return None
        
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(4096):
                f.write(chunk)
        print(f"Successfully downloaded: {filename} ({out_path.stat().st_size} bytes)")
        return out_path
    except Exception as e:
        print(f"Error downloading attachment '{filename}' from {url}: {e}")
        # Try alternative download URLs
        if page_id and att.get('id'):
            alt_urls = [
                f"{CONFLUENCE_URL}/download/attachments/{page_id}/{filename}",
                f"{CONFLUENCE_URL}/download/attachments/{att.get('id')}/{filename}",
                f"{_wiki_base()}/download/attachments/{page_id}/{filename}",
            ]
            for alt_url in alt_urls:
                try:
                    print(f"Trying alternative URL: {alt_url}")
                    r = _get(alt_url, stream=True)
                    content_type = r.headers.get('content-type', '').lower()
                    if 'text/html' not in content_type:
                        with open(out_path, "wb") as f:
                            for chunk in r.iter_content(4096):
                                f.write(chunk)
                        print(f"Successfully downloaded via alternative URL: {filename}")
                        return out_path
                except Exception as alt_e:
                    print(f"Alternative URL failed: {alt_e}")
                    continue
        return None


def rewrite_and_download_attachments(html, page_id, attachments_dir, base_dir):
    soup = BeautifulSoup(html, "html.parser")

    # map available attachments from listing
    try:
        att_list = list_attachments_for_page(page_id)
        print(f"Found {len(att_list)} attachments for page {page_id}")
        
        # Debug: print attachment details
        for att in att_list:
            print(f"Attachment: {att.get('title')} - ID: {att.get('id')} - Links: {att.get('_links', {}).keys()}")
        
        # Create multiple mappings for better filename matching
        att_map = {}
        for att in att_list:
            title = att.get("title")
            if title:
                att_map[title] = att
                # Also map URL-decoded version
                att_map[unquote(title)] = att
                # And map without spaces
                att_map[title.replace(" ", "_")] = att
                # Map with spaces replaced by %20
                att_map[title.replace(" ", "%20")] = att
                
    except Exception as e:
        print(f"Warning: Failed to list attachments for page {page_id}: {e}")
        att_map = {}

    # handle <ri:attachment ri:filename="..."/> (Confluence storage)
    for ri in soup.find_all(lambda tag: tag.name and tag.name.endswith("attachment")):
        filename = ri.attrs.get("ri:filename") or ri.attrs.get("filename")
        if not filename:
            continue
        
        print(f"Processing ri:attachment: {filename}")
        
        # Try multiple filename variations
        filename_variants = [
            filename,
            unquote(filename),
            filename.replace("%20", " "),
            filename.replace("_", " "),
            filename.replace(" ", "_"),
            filename.replace(" ", "%20")
        ]
        
        att = None
        for variant in filename_variants:
            if variant in att_map:
                att = att_map[variant]
                print(f"Found attachment match: {variant}")
                break
        
        if att:
            saved = download_attachment(att, attachments_dir, page_id)
            if saved:
                # Use the Markdown file directory as the base, not the attachments dir
                new_img = soup.new_tag("img", src=str(PathRel(saved, base_dir)))
                ri.replace_with(new_img)
            else:
                # Replace with filename if download failed
                ri.replace_with(f"[Attachment: {filename}]")
        else:
            print(f"Attachment not found in map: {filename}")
            print(f"Available attachments: {list(att_map.keys())}")
            ri.replace_with(f"[Attachment: {filename}]")

    # handle <img src="/download/attachments/..." /> and <a href="/download/attachments/...">
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "/download/attachments/" in src:
            print(f"Processing img src: {src}")
            # Extract filename from URL
            parsed_url = urlparse(src)
            filename = os.path.basename(parsed_url.path)
            if filename:
                filename_variants = [
                    filename,
                    unquote(filename),
                    filename.replace("%20", " "),
                    filename.replace("_", " "),
                    filename.replace(" ", "_"),
                    filename.replace(" ", "%20")
                ]
                
                att = None
                for variant in filename_variants:
                    if variant in att_map:
                        att = att_map[variant]
                        break
                
                if att:
                    saved = download_attachment(att, attachments_dir, page_id)
                    if saved:
                        img["src"] = str(PathRel(saved, base_dir))

    for a in soup.find_all("a"):
        href = a.get("href", "")
        if "/download/attachments/" in href:
            print(f"Processing link href: {href}")
            # Extract filename from URL
            parsed_url = urlparse(href)
            filename = os.path.basename(parsed_url.path)
            if filename:
                filename_variants = [
                    filename,
                    unquote(filename),
                    filename.replace("%20", " "),
                    filename.replace("_", " "),
                    filename.replace(" ", "_"),
                    filename.replace(" ", "%20")
                ]
                
                att = None
                for variant in filename_variants:
                    if variant in att_map:
                        att = att_map[variant]
                        break
                
                if att:
                    saved = download_attachment(att, attachments_dir, page_id)
                    if saved:
                        a["href"] = str(PathRel(saved, base_dir))

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
    proc = subprocess.run(
        ["pandoc", "-f", "html", "-t", "gfm"],
        input=html.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pandoc failed: {proc.stderr.decode()}")
    return proc.stdout.decode("utf-8")


# New: core fetch + save logic refactored into a callable function used by CLI and Streamlit
def fetch_and_save(
    page_id: str = None,
    title_arg: str = None,
    space: str = None,
    out: str = ".",
    use_pandoc: bool = False,
):
    # ensure SESSION initialized explicitly (no env fallback)
    if SESSION is None:
        raise RuntimeError(
            "Credentials not initialized. Call init_session(...) first (e.g., via the Streamlit UI)."
        )

    out_dir = pathlib.Path(out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if page_id:
        page = get_page_by_id(page_id)
    else:
        if not title_arg or not space:
            raise RuntimeError("Both title and space are required when not using page_id")
        page = find_page_by_title(title_arg, space)
        if not page:
            raise RuntimeError(f"Page titled '{title_arg}' not found in space {space}")

    page_id = page.get("id")
    title = page.get("title", f"page-{page_id}")

    # v1 API structure: body.storage.value
    storage = (page.get("body") or {}).get("storage", {}).get("value", "")
    if not storage:
        raise RuntimeError("No storage value found on page.")

    # Use shorter, cleaner attachment directory name
    attachments_dir = out_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    # Pass the Markdown base dir so relative paths are correct
    html_with_local = rewrite_and_download_attachments(
        storage, page_id, attachments_dir, out_dir
    )

    if use_pandoc:
        md = html_to_markdown_via_pandoc(html_with_local)
    else:
        md = html_to_markdown_via_html2text(html_with_local)

    # Save markdown file
    safe_title = "".join(
        c if c.isalnum() or c in " -_." else "_" for c in title
    ).strip()
    md_path = out_dir / f"{safe_title}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(md)

    return {
        "md_path": str(md_path),
        "attachments_dir": str(attachments_dir)
        if any(attachments_dir.iterdir())
        else None,
        "md_content": md,
    }


def main():
    # CLI path: no environment variable support; prefer Streamlit or programmatic init_session
    parser = argparse.ArgumentParser(
        description="Fetch a Confluence page and convert to Markdown."
    )
    parser.add_argument("--page-id", type=str, help="Confluence page ID")
    parser.add_argument(
        "--title", type=str, help="Confluence page title (needs --space)"
    )
    parser.add_argument(
        "--space", type=str, help="Space key (required when using --title)"
    )
    parser.add_argument("--out", type=str, default=".", help="Output directory")
    parser.add_argument(
        "--pandoc", action="store_true", help="Use pandoc for HTML->MD conversion"
    )
    args = parser.parse_args()

    if not args.page_id and not args.title:
        parser.error("Provide --page-id or --title with --space")
    if args.title and not args.space:
        parser.error("--space is required when using --title")

    # Removed environment initialization. Require prior init_session call (not typical for CLI).
    if SESSION is None:
        print(
            "ERROR: Credentials are not set. This tool no longer reads environment variables.\n"
            "Use the Streamlit UI (recommended) or call init_session(...) programmatically before running fetch_and_save."
        )
        sys.exit(1)

    try:
        info = fetch_and_save(
            page_id=args.page_id,
            title_arg=args.title,
            space=args.space,
            out=args.out,
            use_pandoc=args.pandoc,
        )
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

    # credentials (entered in the UI)
    col1, col2 = st.columns(2)
    with col1:
        confluence_url = st.text_input("CONFLUENCE_URL", value="")
        space = st.text_input("Space key (if using title)", value="")
    with col2:
        confluence_user = st.text_input("CONFLUENCE_USER", value="")
        confluence_token = st.text_input(
            "CONFLUENCE_API_TOKEN",
            value="",
            type="password",
        )

    st.markdown("### Page selection")
    page_id = st.text_input("Page ID (leave empty to use Title + Space)", value="")
    title_arg = st.text_input("Page Title (used if Page ID empty)", value="")

    out_dir = st.text_input("Output directory", value=".")
    use_pandoc = st.checkbox("Use pandoc for HTML->MD conversion", value=False)

    if st.button("Fetch"):
        # initialize session with provided values only (no env fallback)
        url = confluence_url
        user = confluence_user
        token = confluence_token
        try:
            init_session(url, user, token)
        except Exception as e:
            st.error(f"Credentials error: {e}")
            return

        with st.spinner("Fetching..."):
            try:
                info = fetch_and_save(
                    page_id=page_id or None,
                    title_arg=title_arg or None,
                    space=space or None,
                    out=out_dir,
                    use_pandoc=use_pandoc,
                )
            except Exception as e:
                st.error(f"Error: {e}")
                return

        st.success(f"Saved: {info['md_path']}")
        if info["attachments_dir"]:
            st.info(f"Attachments saved under: {info['attachments_dir']}")
        # show content and let user download
        st.download_button(
            "Download Markdown",
            data=info["md_content"].encode("utf-8"),
            file_name=os.path.basename(info["md_path"]),
            mime="text/markdown",
        )


# Only decide what to run when executed as a script; never at import time.
def _running_in_streamlit() -> bool:
    try:
        # This import is lightweight and only attempted when __main__
        from streamlit.runtime.scriptrunner import get_script_run_ctx  # type: ignore
        return get_script_run_ctx() is not None
    except Exception:
        return False


if __name__ == "__main__":
    if _running_in_streamlit():
        run_streamlit()
    else:
        main()
