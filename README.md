# Pinterest Gallery Loader — ComfyUI custom node

Search Pinterest from inside a ComfyUI node, click a thumbnail, and load that
pin's full-resolution image as an `IMAGE` output. Infinite-scroll grid, single
selection, selection is saved into the workflow.

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

Running with nothing selected raises a clear node error.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

`scripts/manual_search_check.py "<query>"` hits the live Pinterest endpoint to
sanity-check the request/parse path outside ComfyUI.
