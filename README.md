# Streamlit GitHub Folder Uploader

A phone-friendly Streamlit app that authorizes with GitHub and commits files from a ZIP archive to a new or existing repository.

## Features
- GitHub OAuth login with `state` validation.
- Create a new private/public repository, or use an existing `owner/repo`.
- Upload a ZIP containing a project folder; nested paths are preserved.
- Commits all uploaded files together using the Git database API.
- Supports binary files. Current app limit: 1,000 files and 50 MB total uncompressed ZIP content.

## 1. Create a GitHub OAuth App
On GitHub, open **Settings → Developer settings → OAuth Apps → New OAuth App**.
- Application name: `Streamlit GitHub Uploader`
- Homepage URL: your Streamlit app URL (for local use, `http://localhost:8501`)
- Authorization callback URL: the exact same URL, e.g. `http://localhost:8501`
Copy the Client ID and generate a Client Secret. Keep the secret private.

The app requests the `repo` OAuth scope so it can create repositories and write to private repositories. Review permissions before approving.

## 2. Run locally
Python 3.10+ recommended.

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in your real values:
```toml
GITHUB_CLIENT_ID = "..."
GITHUB_CLIENT_SECRET = "..."
APP_URL = "http://localhost:8501"
```

Then run:
```bash
streamlit run app.py
```

## 3. Deploy on Streamlit Community Cloud
1. Push this project to a GitHub repository (do not include real secrets).
2. Deploy it from Streamlit Community Cloud.
3. In the app's settings, add secrets:
   - `GITHUB_CLIENT_ID`
   - `GITHUB_CLIENT_SECRET`
   - `APP_URL` = the exact public app URL, without a trailing slash.
4. Update the OAuth App's Homepage URL and Authorization callback URL to that same public app URL.
5. Reboot/redeploy the app.

## Use
Create a ZIP of your project folder, preserving the folder/file structure. In the app, sign in, choose new or existing repository, enter the target branch, select the ZIP, and click **Upload and push to GitHub**.

For an existing repository, use `owner/repository`. If the requested branch does not exist, the app creates it based on the repository's default branch.

## Important notes
- The browser uploader uses ZIP files because Streamlit's built-in uploader does not reliably expose folder paths from a direct folder selection.
- Keep the OAuth Client Secret private. Never publish `secrets.toml`, tokens, or secrets in a repository.
- Use this only with repositories you own or are authorized to modify.
- GitHub API permissions, organization policies, branch protection, repository rules, and API limits can prevent an upload.
- This is a starter app, not a fully audited production authentication service. For a public multi-user deployment, consider a GitHub App with minimal permissions, stronger session controls, and security review.
