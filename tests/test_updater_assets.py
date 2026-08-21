from p99_sso_login_proxy import updater


def test_select_update_zip_asset_matches_exact_name():
    assets = [
        {
            "name": "P99LoginProxy-2.0.0-x86_64.AppImage",
            "content_type": "application/vnd.appimage",
            "browser_download_url": "https://example.com/appimage",
        },
        {
            "name": "P99LoginProxy-2.0.0.zip",
            "content_type": "application/zip",
            "browser_download_url": "https://example.com/zip",
        },
    ]
    assert updater.select_update_zip_asset(assets, "2.0.0") == "https://example.com/zip"


def test_select_update_zip_asset_ignores_other_zips():
    assets = [
        {
            "name": "other.zip",
            "content_type": "application/zip",
            "browser_download_url": "https://example.com/wrong",
        }
    ]
    assert updater.select_update_zip_asset(assets, "2.0.0") is None
