from importlib import resources as importlib_resources


def test_packaged_assets_present():
    tpl = importlib_resources.files("signal_export").joinpath("assets", "template.html")
    css = importlib_resources.files("signal_export").joinpath("assets", "styles.css")
    assert tpl.is_file()
    assert css.is_file()
