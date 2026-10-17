import base64
import hmac
import io
import re
import secrets
import zipfile
from urllib.parse import quote, urlencode

import requests
import streamlit as st
from streamlit_cookies_controller import CookieController


# ---------- App settings ----------

st.set_page_config(
    page_title="GitHub Folder Uploader",
    page_icon="📦",
    layout="centered",
)

APP_URL = "https://9l72f7zvvhtrplk3jjdkh3.streamlit.app"
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"

MAX_FILES = 2000
MAX_TOTAL_SIZE = 100 * 1024 * 1024
MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_ZIP_SIZE = 100 * 1024 * 1024

st.title("📦 GitHub Folder Uploader")
st.write(
    "Upload a ZIP project. Its folders and files will be "
    "created individually in your GitHub repository."
)

# Secrets must be configured in Streamlit Cloud.
try:
    CLIENT_ID = st.secrets["GITHUB_CLIENT_ID"]
    CLIENT_SECRET = st.secrets["GITHUB_CLIENT_SECRET"]
except Exception:
    CLIENT_ID = ""
    CLIENT_SECRET = ""

cookies = CookieController()


# ---------- GitHub helpers ----------

def github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def safe_repo_name(value):
    value = value.strip()
    parts = value.split("/")
    return (
        len(parts) == 2
        and all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts)
        and parts[0] not in ("", ".", "..")
        and parts[1] not in ("", ".", "..")
    )


def safe_zip_path(name):
    name = name.replace("\\", "/")

    if name.startswith("/") or "\x00" in name:
        return None

    parts = name.split("/")

    if any(p in ("", ".", "..") for p in parts):
        return None

    # Do not upload Git's internal repository metadata.
    if ".git" in parts:
        return None

    # Skip common macOS ZIP metadata.
    if "__MACOSX" in parts or parts[-1] == ".DS_Store":
        return None

    return "/".join(parts)


def github_contents_url(repo, path):
    owner, repository = repo.split("/", 1)
    encoded_path = quote(path, safe="/")
    return (
        f"{GITHUB_API_URL}/repos/{owner}/"
        f"{repository}/contents/{encoded_path}"
    )


def upload_one_file(token, repo, path, data):
    headers = github_headers(token)
    url = github_contents_url(repo, path)

    # If the file already exists, get its SHA so it can be updated.
    check = requests.get(url, headers=headers, timeout=30)

    payload = {
        "message": f"Upload {path} using GitHub Folder Uploader",
        "content": base64.b64encode(data).decode("ascii"),
    }

    if check.status_code == 200:
        payload["sha"] = check.json()["sha"]
    elif check.status_code != 404:
        message = check.json().get("message", check.text)
        raise RuntimeError(
            f"Could not check {path}: HTTP "
            f"{check.status_code} — {message}"
        )

    result = requests.put(
        url,
        headers=headers,
        json=payload,
        timeout=60,
    )

    if result.status_code not in (200, 201):
        try:
            message = result.json().get("message", result.text)
        except ValueError:
            message = result.text

        raise RuntimeError(
            f"{path}: HTTP {result.status_code} — {message}"
        )


def upload_zip(token, repo, uploaded_file):
    zip_bytes = uploaded_file.getvalue()

    if len(zip_bytes) > MAX_ZIP_SIZE:
        st.error("ZIP file is too large. Maximum size is 100 MB.")
        return

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except (zipfile.BadZipFile, OSError):
        st.error("The selected file is not a valid ZIP.")
        return

    with archive:
        entries = []
        total_size = 0

        for info in archive.infolist():
            if info.is_dir():
                continue

            path = safe_zip_path(info.filename)

            if path is None:
                st.error(
                    "ZIP contains an unsafe path or unsupported "
                    f"metadata entry: {info.filename}"
                )
                return

            # Reject symbolic links.
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if (unix_mode & 0o170000) == 0o120000:
                st.error(f"Symbolic links are not supported: {path}")
                return

            if info.file_size > MAX_FILE_SIZE:
                st.error(
                    f"{path} is larger than the 25 MB per-file limit."
                )
                return

            total_size += info.file_size
            entries.append((info, path))

        if not entries:
            st.error("No project files were found in the ZIP.")
            return

        if len(entries) > MAX_FILES:
            st.error(f"Too many files. Limit: {MAX_FILES}.")
            return

        if total_size > MAX_TOTAL_SIZE:
            st.error("The uncompressed project exceeds 100 MB.")
            return

        progress = st.progress(0)
        status = st.empty()
        uploaded_count = 0

        for index, (info, path) in enumerate(entries):
            status.write(f"Uploading {index + 1}/{len(entries)}: `{path}`")

            try:
                data = archive.read(info)
                upload_one_file(token, repo, path, data)
            except Exception as exc:
                st.error(f"Upload stopped: {exc}")
                st.info(
                    "Some earlier files may already have been uploaded. "
                    "Fix the error and try again."
                )
                return

            uploaded_count += 1
            progress.progress(uploaded_count / len(entries))

        status.success(
            f"Finished! {uploaded_count} files uploaded to GitHub."
        )
        st.link_button(
            "Open GitHub repository",
            f"https://github.com/{repo}",
        )


# ---------- OAuth callback ----------

params = st.query_params
auth_code = params.get("code")
returned_state = params.get("state")

if params.get("error"):
    st.error(
        "GitHub login was cancelled or denied. "
        "Please try again."
    )
    st.query_params.clear()
    st.stop()

if auth_code:
    saved_state = cookies.get("oauth_state")

    if (
        not saved_state
        or not returned_state
        or not hmac.compare_digest(
            str(saved_state), str(returned_state)
        )
    ):
        st.error(
            "OAuth state mismatch. The browser did not return "
            "the expected login cookie. Start login again in the "
            "same browser, with cookies enabled."
        )
        if st.button("Clear login attempt"):
            cookies.remove("oauth_state")
            st.session_state.pop("pending_oauth_state", None)
            st.query_params.clear()
            st.rerun()
        st.stop()

    # State matched; remove the one-time cookie.
    cookies.remove("oauth_state")
    st.session_state.pop("pending_oauth_state", None)

    if not CLIENT_ID or not CLIENT_SECRET:
        st.error("GitHub OAuth credentials are missing in Streamlit Secrets.")
        st.stop()

    try:
        response = requests.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": auth_code,
                "redirect_uri": APP_URL,
            },
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
    except Exception:
        st.error("Could not exchange the GitHub authorization code.")
        st.stop()

    access_token = token_data.get("access_token")

    if not access_token:
        st.error("GitHub did not return an access token.")
        st.stop()

    st.session_state["github_token"] = access_token
    st.query_params.clear()
    st.rerun()


# ---------- Login screen ----------

token = st.session_state.get("github_token")

if not token:
    st.subheader("1. Sign in with GitHub")

    if not CLIENT_ID or not CLIENT_SECRET:
        st.error(
            "Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET "
            "in Streamlit Cloud → App settings → Secrets."
        )
        st.stop()

    if st.button("Prepare GitHub login", type="primary"):
        state = secrets.token_urlsafe(32)
        cookies.set("oauth_state", state)
        st.session_state["pending_oauth_state"] = state

    pending_state = st.session_state.get("pending_oauth_state")
    cookie_state = cookies.get("oauth_state")

    if pending_state and cookie_state == pending_state:
        auth_query = urlencode({
            "client_id": CLIENT_ID,
            "redirect_uri": APP_URL,
            "scope": "repo",
            "state": pending_state,
        })

        st.link_button(
            "Continue with GitHub",
            f"{GITHUB_AUTH_URL}?{auth_query}",
            type="primary",
        )
    elif pending_state:
        st.warning(
            "The browser cookie is not ready yet. "
            "Tap Check cookie, then continue."
        )
        if st.button("Check cookie"):
            st.rerun()

    st.stop()


# ---------- Upload screen ----------

st.success("GitHub login successful!")
st.subheader("2. Upload your project ZIP")

repo = st.text_input(
    "Target repository (owner/repository)",
    placeholder="yourusername/your-repository",
)

uploaded_zip = st.file_uploader(
    "Choose your project ZIP",
    type=["zip"],
    help="Files and nested folders will be uploaded separately.",
)

if st.button("Upload folders and files", type="primary"):
    if not safe_repo_name(repo):
        st.error("Enter the repository as owner/repository.")
    elif uploaded_zip is None:
        st.error("Choose a ZIP file first.")
    else:
        upload_zip(token, repo, uploaded_zip)


if st.button("Logout"):
    st.session_state.pop("github_token", None)
    st.session_state.pop("pending_oauth_state", None)
    cookies.remove("oauth_state")
    st.rerun()
