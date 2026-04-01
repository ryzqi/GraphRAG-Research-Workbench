from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SETTINGS_PATH = ROOT / 'infra' / 'searxng' / 'config' / 'settings.yml'
VERIFY_SCRIPT_PATH = ROOT / 'scripts' / 'verify_quickstart.ps1'


def test_searxng_settings_enable_default_engine_catalog() -> None:
    text = SETTINGS_PATH.read_text(encoding='utf-8')

    assert 'use_default_settings: true' in text
    assert 'keep_only:' not in text, '启用所有 SearXNG 默认引擎时不应再保留 keep_only 白名单'
    assert 'SearxEngineAccessDenied: 120' in text
    assert 'SearxEngineTooManyRequests: 120' in text
    assert 'SearxEngineCaptcha: 1800' in text
    assert 'retries: 2' in text


def test_verify_quickstart_reports_active_engine_inventory() -> None:
    text = VERIFY_SCRIPT_PATH.read_text(encoding='utf-8')

    assert 'Get-SearXngActiveEngineCount' in text
    assert 'SearXNG 活跃引擎数' in text
    assert '全量默认引擎集' in text
