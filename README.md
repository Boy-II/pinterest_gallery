# Pinterest Gallery Loader — ComfyUI custom node

Search Pinterest, filter by image orientation, and select a reference image
directly in a ComfyUI node. The expanded gallery shows larger previews.
With an authorized Pinterest account, you can browse your boards and save
an existing Pin to a board you own. The selected image is saved in the
workflow as a reference and loads as an `IMAGE` output when run.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Boy-II/pinterest_gallery
```

Install the dependencies into the **same** Python ComfyUI runs on:

```bash
python -m pip install -r pinterest_gallery/requirements.txt
```

For a portable Windows build, run the equivalent command from the portable
installation directory. Use the Python interpreter supplied with your build.

```bat
python_embeded\python.exe -m pip install -r ComfyUI\custom_nodes\pinterest_gallery\requirements.txt
```

Restart ComfyUI. The node appears as **Pinterest Gallery Loader** under
`image/pinterest`.

### Optional: My Boards mode

Public search works without an account connection. Open **设置** on the node or
**连接 Pinterest** in the expanded gallery to enter an existing access token or
authorize through Pinterest. Both methods require an approved Pinterest
Developer App and permission to read boards and standard Pins. For browser
authorization, register the exact callback URL shown in the gallery under
your app's **Redirect URIs**.
Choose **Production** for your regular boards or **Sandbox** for sandbox data.

For command-line setup, pass the token in the environment of the Python process
that launches ComfyUI.

PowerShell:

```powershell
$env:PINTEREST_ACCESS_TOKEN = "your-token"
$env:PINTEREST_API_ENV = "sandbox"  # use "production" for a production token
python main.py
```

Keep the token out of workflow files, source code, test fixtures, and logs.
The in-app connection form sends it directly to the local ComfyUI backend.
On Windows, **在本机加密保存连接** stores the access token encrypted for your
Windows account.

OAuth requests read access by default. **加入画板** can request write access.
Saving requires a verifiable Pin ID, a board you own, and your confirmation.
The save picker lists ordinary boards. If a public search result lacks a
verifiable Pin ID, you can still select the image for a workflow.

Open ComfyUI directly on its local loopback address for account settings and
saving. Keep account management, account board browsing, and Pin-saving routes
private when configuring remote access or a reverse proxy.

Sandbox tokens must use the Sandbox API environment. Production tokens must use
the production API environment; set `PINTEREST_API_ENV` accordingly.

`PINTEREST_API_ENV` accepts `sandbox` or `production` and defaults to
`sandbox`. An invalid value only affects account browsing. Public search
remains available.

## Update

```bash
cd ComfyUI/custom_nodes/pinterest_gallery && git pull
```

## Usage

1. Add **Pinterest Gallery Loader**.
2. Search directly in the node, or select **我的画板** after connecting your account.
3. Filter by orientation and click a thumbnail to set the workflow input.
   **展开画廊** opens the full gallery with the current search, results, and selection.
4. Click **加入画板** on a Pin, choose a destination board, and confirm. Pinterest
   requires a verified Pin ID and write permission. The connection form requests
   write permission when opened from this action.
5. Queue the workflow to return the full-size image through its
   existing `IMAGE` output.

Running with nothing selected raises a clear node error.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

`scripts/manual_search_check.py "<query>"` hits the live Pinterest endpoint to
sanity-check the request/parse path outside ComfyUI.
