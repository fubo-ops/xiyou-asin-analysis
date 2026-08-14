import json

from tools.verify_phase2 import read_source_status


def test_missing_sqp_status_is_reported_as_missing_data(tmp_path):
    status_path = tmp_path / "status" / "amazon-search-query-performance.json"

    status = read_source_status(status_path)

    assert status == {
        "source_name": "AMAZON_SEARCH_QUERY_PERFORMANCE",
        "status": "MISSING_DATA",
        "reason": "未找到 SQP 状态文件；没有同周期 SQP 请求或结果",
    }


def test_existing_sqp_status_is_loaded_unchanged(tmp_path):
    status_path = tmp_path / "status.json"
    expected = {"source_name": "AMAZON_SEARCH_QUERY_PERFORMANCE", "status": "AVAILABLE_EMPTY"}
    status_path.write_text(json.dumps(expected), encoding="utf-8")

    assert read_source_status(status_path) == expected
