"""extract_error_codes 白名单改造的单元测试

验收标准一：零误抠——日志时间戳/数值/序列号不误判为报警码，
纯数字码仅在手册码表（白名单）内匹配；混合码照旧自由匹配。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.tools import extract_error_codes

# 测试用码表（与种子数据一致：SV0436/SV0401/PS0002/EX1006/6401/6500/R0910/E3091）
_SEED_WHITELIST = {
    "SV0436", "SV0401", "PS0002", "EX1006", "6401", "6500", "R0910", "E3091",
}


class TestExtractErrorCodes:
    """日志噪声 → 零误抠"""

    @pytest.mark.parametrize("text", [
        "2026-08-14 10:32:15",
        "转速 1234 rpm，温度 45.2°C",
        "电压 380V，电流 12.5A",
        "S/N 20260015",
        "设备编号 20260814，位置 A3",
        "参数 1829 需要调整",
    ])
    def test_log_noise_returns_empty(self, text):
        assert extract_error_codes(text, whitelist=_SEED_WHITELIST) == []

    """混合码 → 自由匹配"""

    @pytest.mark.parametrize("text,expected", [
        ("SV0436 报警", ["SV0436"]),
        ("ALM-6401", ["ALM6401"]),
        ("X轴伺服放大器过流 SV0436", ["SV0436"]),
        ("2026-08-14 10:32:15 SV0436 X AXIS: EXCESS CURRENT", ["SV0436"]),
    ])
    def test_mixed_codes_free_match(self, text, expected):
        assert extract_error_codes(text, whitelist=_SEED_WHITELIST) == expected

    """纯数字码 → 白名单过滤"""

    def test_numeric_code_in_whitelist(self):
        assert extract_error_codes("6401", whitelist=_SEED_WHITELIST) == ["6401"]

    def test_numeric_code_not_in_whitelist(self):
        assert extract_error_codes("0401", whitelist=_SEED_WHITELIST) == []

    def test_mixed_code_does_not_duplicate_numeric_part(self):
        # ALM-6401 只出 ALM6401，不再单独抠出 6401
        assert extract_error_codes("ALM-6401", whitelist=_SEED_WHITELIST) == ["ALM6401"]

    def test_empty_query(self):
        assert extract_error_codes("", whitelist=_SEED_WHITELIST) == []
