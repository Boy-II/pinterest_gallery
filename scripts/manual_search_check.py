import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pinterest_gallery.pinterest_api import PinterestClient


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "cyberpunk city"
    client = PinterestClient()
    items, bookmark = client.search(query)
    print(f"query={query!r} got {len(items)} items, bookmark={bookmark!r}")
    for item in items[:3]:
        print(item)


if __name__ == "__main__":
    main()
