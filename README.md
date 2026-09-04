# Pinterest Gallery Loader — ComfyUI custom node

Search Pinterest from inside a ComfyUI node, browse your own Boards with a
Pinterest API token, click a thumbnail, and load that pin's full-resolution
image as an `IMAGE` output. Infinite-scroll grid, single selection, selection
is saved into the workflow.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Boy-II/pinterest_gallery
```

Then install the one runtime dependency into the **same** Python ComfyUI runs on:

```bash
python -m pip install -r pinterest_gallery/requirements.txt   # just: requests
```

For the ComfyUI-aki portable build on Windows the embedded interpreter is
`E:\ComfyUI-aki-v2\python\python.exe` (some builds name it `python_embeded`):

```bat
"E:\ComfyUI-aki-v2\python\python.exe" -m pip install requests
```

Restart ComfyUI. The node appears as **Pinterest Gallery Loader** under
`image/pinterest`.

### Optional: My Boards mode

Search mode works without a token. To enable **My Boards**, create a Pinterest
App and generate a sandbox or production access token with read access to
Boards and standard Pins. Set the token only in the environment of the Python
process that launches ComfyUI:

PowerShell:

```powershell
$env:PINTEREST_ACCESS_TOKEN = "your-token"
$env:PINTEREST_API_ENV = "sandbox"  # use "production" for a production token
python main.py
```

Do not put the token in a workflow, source file, fixture, log, or browser
request. The node sends it only from the Python backend to Pinterest's API.

The first version reads Boards and Pins only. It does not create, edit, delete,
or publish Pinterest content, and it does not support Secret Boards.

Sandbox tokens must use the Sandbox API environment. Production tokens must use
the production API environment; set `PINTEREST_API_ENV` accordingly.

## Update

```bash
cd ComfyUI/custom_nodes/pinterest_gallery && git pull
```

## Usage

1. Add **Pinterest Gallery Loader**.
2. Type a query — thumbnails load in a 3-column grid.
3. Scroll the grid — more results load automatically.
4. Click a thumbnail — green border marks the selection.
5. Wire the `IMAGE` output onward and queue the prompt; the full original-size
   image is downloaded at run time.
6. To browse your account, switch the mode selector to **My Boards**, choose a
   Board, and scroll the grid to load more Pins.

Running with nothing selected raises a clear node error.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

`scripts/manual_search_check.py "<query>"` hits the live Pinterest endpoint to
sanity-check the request/parse path outside ComfyUI.
