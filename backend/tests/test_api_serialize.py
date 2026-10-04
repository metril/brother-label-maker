"""Tests for task 2.4's serialization-support endpoints: POST
/api/render/expand (distinct values + optional sample expansion, no
rendering) and POST /api/serialize/csv (stateless CSV upload echo).

Preview-with-serialization and print-with-serialization (the two endpoints
that actually RENDER/PRINT a serialized run) are covered in
test_api_preview.py and test_api_print.py respectively, alongside their
existing byte-parity/e2e conventions.
"""

from __future__ import annotations

import io


def _numeric(**overrides) -> dict:
    body = {"kind": "numeric", "start": 1, "step": 1, "count": 3}
    body.update(overrides)
    return body


# --- 1. POST /api/render/expand -- values + total_labels -------------------


async def test_expand_numeric_returns_distinct_values_and_total(client):
    resp = await client.post(
        "/api/render/expand", json={"serialization": _numeric(copies_per_value=2)}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["values"] == ["1", "2", "3"]  # distinct values only, no copies
    assert body["total_labels"] == 6  # 3 distinct x 2 copies
    assert body["samples"] is None  # no `sample` template was given


async def test_expand_pad_width_zero_pads_numeric_values(client):
    resp = await client.post(
        "/api/render/expand",
        json={"serialization": _numeric(start=1, step=1, count=3, pad_width=3)},
    )
    assert resp.status_code == 200
    assert resp.json()["values"] == ["001", "002", "003"]


# --- 2. POST /api/render/expand -- `sample` -> `samples` -------------------


async def test_expand_with_sample_substitutes_seq_token(client):
    resp = await client.post(
        "/api/render/expand",
        json={"serialization": _numeric(), "sample": "Port {seq}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["samples"] == ["Port 1", "Port 2", "Port 3"]


async def test_expand_samples_capped_at_24_distinct_values(client):
    values = [f"v{i}" for i in range(30)]
    resp = await client.post(
        "/api/render/expand",
        json={
            "serialization": {"kind": "list", "values": values},
            "sample": "X{seq}",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_labels"] == 30
    assert len(body["samples"]) == 24
    assert body["samples"] == [f"X{v}" for v in values[:24]]


async def test_expand_csv_sample_substitutes_csv_columns_per_row(client):
    resp = await client.post(
        "/api/render/expand",
        json={
            "serialization": {
                "kind": "csv",
                "rows": [{"port": "1", "name": "Alice"}, {"port": "2", "name": "Bob"}],
            },
            "sample": "{csv.name} ({csv.port})",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["samples"] == ["Alice (1)", "Bob (2)"]


async def test_expand_csv_sample_unknown_column_returns_422_listing_available(client):
    resp = await client.post(
        "/api/render/expand",
        json={
            "serialization": {"kind": "csv", "rows": [{"port": "1"}]},
            "sample": "{csv.missing}",
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "missing" in detail
    assert "port" in detail


# --- 3. POST /api/render/expand -- runtime ValueErrors -> 422 --------------


async def test_expand_alpha_underflow_returns_422(client):
    resp = await client.post(
        "/api/render/expand",
        json={"serialization": {"kind": "alpha", "alpha_start": "A", "step": -1, "count": 2}},
    )
    assert resp.status_code == 422
    assert "A" in resp.json()["detail"]


async def test_expand_alpha_beyond_zzz_returns_422(client):
    resp = await client.post(
        "/api/render/expand",
        json={"serialization": {"kind": "alpha", "alpha_start": "ZZZ", "step": 1, "count": 2}},
    )
    assert resp.status_code == 422


# --- 4. POST /api/render/expand -- request-shape validation (automatic) ----


async def test_expand_kind_list_empty_values_returns_422(client):
    resp = await client.post(
        "/api/render/expand", json={"serialization": {"kind": "list", "values": []}}
    )
    assert resp.status_code == 422


async def test_expand_total_over_1000_returns_422(client):
    resp = await client.post(
        "/api/render/expand",
        json={"serialization": _numeric(count=500, copies_per_value=3)},
    )
    assert resp.status_code == 422


# --- 5. POST /api/serialize/csv -- happy path -------------------------------


async def test_csv_upload_happy_path(client):
    csv_text = "port,name\n1,Alice\n2,Bob\n3,Carol\n"
    resp = await client.post(
        "/api/serialize/csv",
        files={"file": ("ports.csv", io.BytesIO(csv_text.encode()), "text/csv")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["columns"] == ["port", "name"]
    assert body["rows"] == [
        {"port": "1", "name": "Alice"},
        {"port": "2", "name": "Bob"},
        {"port": "3", "name": "Carol"},
    ]
    assert body["row_count"] == 3


async def test_csv_upload_result_is_a_valid_serialization_csv_rows_payload(client):
    # The whole point of this endpoint: its `rows` output must be directly
    # postable as Sequence(kind=csv, rows=...) without transformation.
    csv_text = "a,b\n1,2\n"
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("t.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    )
    rows = resp.json()["rows"]
    expand_resp = await client.post(
        "/api/render/expand", json={"serialization": {"kind": "csv", "rows": rows}}
    )
    assert expand_resp.status_code == 200
    assert expand_resp.json()["total_labels"] == 1


# --- 6. POST /api/serialize/csv -- rejections -------------------------------


async def test_csv_upload_empty_file_returns_422(client):
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    )
    assert resp.status_code == 422


async def test_csv_upload_header_only_no_data_rows_returns_422(client):
    resp = await client.post(
        "/api/serialize/csv",
        files={"file": ("header.csv", io.BytesIO(b"a,b\n"), "text/csv")},
    )
    assert resp.status_code == 422


async def test_csv_upload_ragged_row_returns_422(client):
    csv_text = "a,b,c\n1,2,3\n4,5\n"  # row 2 (line 3) has only 2 fields, expected 3
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("t.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    )
    assert resp.status_code == 422
    assert "3" in resp.json()["detail"]


async def test_csv_upload_duplicate_header_returns_422(client):
    csv_text = "a,b,a\n1,2,3\n"
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("t.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    )
    assert resp.status_code == 422
    assert "a" in resp.json()["detail"]


async def test_csv_upload_over_500_rows_returns_422(client):
    lines = ["a"] + [str(i) for i in range(501)]
    csv_text = "\n".join(lines) + "\n"
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("big.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    )
    assert resp.status_code == 422
    assert "500" in resp.json()["detail"]


async def test_csv_upload_502_rows_rejected_via_early_bail(client):
    # Review fix-up: the row cap used to be enforced AFTER the whole file
    # was parsed into `rows` (a 2M-row upload drove RSS 115MB->910MB before
    # the 422). It's now checked inside the parse loop, bailing as soon as
    # row MAX_CSV_ROWS+1 is read -- this pins that the endpoint still
    # rejects correctly (can't assert memory from a test; the loop-bail
    # itself, exercised here, is the fix -- see router_labels.py's
    # upload_serialize_csv).
    lines = ["a"] + [str(i) for i in range(502)]
    csv_text = "\n".join(lines) + "\n"
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("big.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    )
    assert resp.status_code == 422
    assert "500" in resp.json()["detail"]


async def test_csv_upload_exactly_500_rows_accepted(client):
    lines = ["a"] + [str(i) for i in range(500)]
    csv_text = "\n".join(lines) + "\n"
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("big.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    )
    assert resp.status_code == 200
    assert resp.json()["row_count"] == 500


async def test_csv_upload_blank_trailing_line_is_not_treated_as_ragged(client):
    csv_text = "a,b\n1,2\n\n"  # trailing blank line after the last data row
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("t.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    )
    assert resp.status_code == 200
    assert resp.json()["row_count"] == 1


async def test_csv_upload_strips_whitespace_from_row_values_like_headers(client):
    # Header column names are already stripped -- row VALUES get the same
    # treatment (a common spreadsheet-export artifact: " Alice" / "Bob "),
    # so a {csv.name} substitution never carries stray leading/trailing
    # whitespace through from an untrimmed cell.
    csv_text = "port,name\n 1 , Alice \n"
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("t.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    )
    assert resp.status_code == 200
    assert resp.json()["rows"] == [{"port": "1", "name": "Alice"}]


async def test_csv_upload_over_1mib_is_413(client):
    big = b"a,b\n" + b"1,2\n" * 300_000  # ~1.2 MB
    resp = await client.post(
        "/api/serialize/csv", files={"file": ("big.csv", io.BytesIO(big), "text/csv")}
    )
    assert resp.status_code == 413
