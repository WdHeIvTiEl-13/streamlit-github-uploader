import base64
import os
import secrets
from urllib.parse import urlencode

import requests
import streamlit as st

GITHUB_API = "https://api.github.com"
GITHUB_AUTH = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"

st.set_page_config(page_title="GitHub Folder Uploader", page_icon="📦", layout="centered")
st.title("📦 GitHub Folder Uploader")
st.caption("Upload a ZIP folder and publish its files to a new or existing GitHub repository.")

def secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return os.getenv(name, default)

CLIENT_ID = secret("GITHUB_CLIENT_ID")
CLIENT_SECRET = secret("GITHUB_CLIENT_SECRET")
APP_URL = secret("APP_URL", "").rstrip("/")

def api_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def api_request(method, path, token, **kwargs):
    response = requests.request(
        method, f"{GITHUB_API}{path}", headers=api_headers(token),
        timeout=30, **kwargs
    )
    if not response.ok:
        try:
            message = response.json().get("message", response.text)
        except Exception:
            message = response.text
        raise RuntimeError(f"GitHub API ({response.status_code}): {message}")
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()

def exchange_code(code):
    response = requests.post(
        GITHUB_TOKEN,
        headers={"Accept": "application/json"},
        data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": code},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if "access_token" not in data:
        raise RuntimeError(data.get("error_description", data.get("error", "OAuth login failed")))
    return data["access_token"]

def clean_zip(upload):
    import io, zipfile
    result = []
    total = 0
    max_files = 1000
    max_total = 50 * 1024 * 1024
    with zipfile.ZipFile(io.BytesIO(upload.getvalue())) as zf:
        entries = [x for x in zf.infolist() if not x.is_dir()]
        if len(entries) > max_files:
            raise ValueError(f"ZIP-e beshi file ache. Maximum {max_files} files.")
        for item in entries:
            name = item.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if not parts or any(p == ".." for p in parts) or name.startswith("/"):
                continue
            if item.flag_bits & 0x1:
                raise ValueError("Password-protected ZIP support kore na.")
            content = zf.read(item)
            total += len(content)
            if total > max_total:
                raise ValueError("Uncompressed total size 50 MB-er beshi. Choto ZIP upload korun.")
            result.append(( "/".join(parts), content))
    if not result:
        raise ValueError("ZIP-er moddhe kono valid file paoa jayni.")
    return result

def create_repo(token, name, private, description):
    return api_request(
        "POST", "/user/repos", token,
        json={"name": name, "private": private, "description": description, "auto_init": True},
    )

def upload_commit(token, owner, repo, branch, files, message):
    # Get the target branch and its base tree. If branch does not exist, start from default branch.
    repo_info = api_request("GET", f"/repos/{owner}/{repo}", token)
    default_branch = repo_info.get("default_branch") or "main"
    try:
        ref = api_request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}", token)
        parent_sha = ref["object"]["sha"]
        commit = api_request("GET", f"/repos/{owner}/{repo}/git/commits/{parent_sha}", token)
        base_tree = commit["tree"]["sha"]
        parent_commits = [parent_sha]
        create_branch_ref = False
    except RuntimeError as e:
        # If target branch is absent, use default branch as parent and create the requested ref afterward.
        if "404" not in str(e):
            raise
        default_ref = api_request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{default_branch}", token)
        parent_sha = default_ref["object"]["sha"]
        default_commit = api_request("GET", f"/repos/{owner}/{repo}/git/commits/{parent_sha}", token)
        base_tree = default_commit["tree"]["sha"]
        parent_commits = [parent_sha]
        create_branch_ref = True

    tree_items = []
    for path, content in files:
        blob = api_request(
            "POST", f"/repos/{owner}/{repo}/git/blobs", token,
            json={"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
        )
        tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

    new_tree = api_request(
        "POST", f"/repos/{owner}/{repo}/git/trees", token,
        json={"base_tree": base_tree, "tree": tree_items},
    )
    new_commit = api_request(
        "POST", f"/repos/{owner}/{repo}/git/commits", token,
        json={"message": message or "Upload files with Streamlit GitHub Uploader",
              "tree": new_tree["sha"], "parents": parent_commits},
    )

    if create_branch_ref:
        api_request(
            "POST", f"/repos/{owner}/{repo}/git/refs", token,
            json={"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]},
        )
    else:
        api_request(
            "PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}", token,
            json={"sha": new_commit["sha"], "force": False},
        )
    return new_commit["sha"]

# OAuth callback processing
params = st.query_params
if params.get("error"):
    st.error("GitHub login cancel/failed hoyeche: " + str(params.get("error_description", params.get("error"))))
    st.query_params.clear()
if params.get("code"):
    expected = st.session_state.get("oauth_state")
    returned = params.get("state")
    if not expected or not returned or not secrets.compare_digest(str(expected), str(returned)):
        st.error("OAuth state mismatch. Security-r jonno abar login korun.")
        st.query_params.clear()
    elif not CLIENT_ID or not CLIENT_SECRET:
        st.error("GitHub OAuth secrets configure kora nei.")
    else:
        try:
            st.session_state["github_token"] = exchange_code(str(params.get("code")))
            st.session_state.pop("oauth_state", None)
            st.query_params.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Login error: {e}")
            st.query_params.clear()

if not CLIENT_ID or not CLIENT_SECRET:
    st.warning("Age GitHub OAuth app setup korun. README-te step-by-step instruction ache.")
    st.stop()

if "github_token" not in st.session_state:
    st.write("GitHub account connect kore ZIP-er files upload korun.")
    if st.button("Continue with GitHub", type="primary", use_container_width=True):
        state = secrets.token_urlsafe(24)
        st.session_state["oauth_state"] = state
        callback = APP_URL or st.context.url.split("?")[0]
        query = urlencode({"client_id": CLIENT_ID, "redirect_uri": callback,
                           "scope": "repo", "state": state})
        st.link_button("Open GitHub authorization", f"{GITHUB_AUTH}?{query}", use_container_width=True)
    st.caption("Login button click korar por GitHub authorization page-e approve korte hobe.")
    st.stop()

token = st.session_state["github_token"]
try:
    user = api_request("GET", "/user", token)
    st.success(f"Connected as **@{user.get('login', 'GitHub user')}**")
except Exception:
    st.session_state.pop("github_token", None)
    st.error("GitHub session invalid hoyeche. Page refresh kore abar login korun.")
    st.stop()

with st.form("upload_form"):
    mode = st.radio("Repository", ["Create new repository", "Use existing repository"])
    if mode == "Create new repository":
        repo_name = st.text_input("New repository name", placeholder="my-project")
        private = st.checkbox("Private repository", value=True)
        description = st.text_input("Description (optional)")
        owner = user.get("login", "")
    else:
        repo_full = st.text_input("Existing repository", placeholder="username/repository")
        owner = ""
        repo_name = ""
        private = True
        description = ""
    branch = st.text_input("Branch name", value="main")
    commit_message = st.text_input("Commit message", value="Upload project files")
    zip_file = st.file_uploader("Project folder as ZIP", type=["zip"])
    submitted = st.form_submit_button("Upload and push to GitHub", type="primary", use_container_width=True)

if submitted:
    try:
        if not zip_file:
            raise ValueError("Age project folder-er ZIP file select korun.")
        if mode == "Create new repository":
            if not repo_name.strip():
                raise ValueError("Repository name din.")
            repo_info = create_repo(token, repo_name.strip(), private, description.strip())
            owner, repo_name = repo_info["owner"]["login"], repo_info["name"]
        else:
            bits = [x.strip() for x in repo_full.split("/")]
            if len(bits) != 2 or not all(bits):
                raise ValueError("Repository format hobe username/repository.")
            owner, repo_name = bits
        if not branch.strip() or any(c in branch for c in " ~^:?*[\\"):
            raise ValueError("Valid branch name din.")
        files = clean_zip(zip_file)
        with st.spinner(f"{len(files)} ta file GitHub-e upload hocche..."):
            sha = upload_commit(token, owner, repo_name, branch.strip(), files, commit_message.strip())
        st.success(f"Upload complete! {len(files)} ta file commit hoyeche.")
        st.markdown(f"[Open repository](https://github.com/{owner}/{repo_name})")
        st.code(sha)
    except Exception as e:
        st.error(str(e))

st.divider()
if st.button("Disconnect GitHub", use_container_width=True):
    st.session_state.pop("github_token", None)
    st.session_state.pop("oauth_state", None)
    st.rerun()
st.caption("Security: access token sudhu current Streamlit session-e rakha hoy; app code/log-e token print kora hoy na.")
