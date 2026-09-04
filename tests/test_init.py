import pinterest_gallery
from pinterest_gallery.nodes import PinterestGalleryLoader


def test_package_exports_node_mappings():
    assert pinterest_gallery.NODE_CLASS_MAPPINGS == {
        "PinterestGalleryLoader": PinterestGalleryLoader
    }
    assert pinterest_gallery.NODE_DISPLAY_NAME_MAPPINGS == {
        "PinterestGalleryLoader": "Pinterest Gallery Loader"
    }
    assert pinterest_gallery.WEB_DIRECTORY == "web"
