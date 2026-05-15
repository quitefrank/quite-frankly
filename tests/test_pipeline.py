from pipeline import assign_ids, monday_dedup_bypass


def test_assign_ids_returns_dict_keyed_by_id():
    items = [
        {"title": "a", "link": "u1", "source": "CBC"},
        {"title": "b", "link": "u2", "source": "BBC"},
    ]
    by_id = assign_ids(items)
    assert by_id == {0: items[0], 1: items[1]}


def test_assign_ids_attaches_id_to_each_item():
    items = [{"title": "a", "link": "u1", "source": "CBC"}]
    by_id = assign_ids(items)
    assert by_id[0]["id"] == 0


def test_monday_bypass_keeps_items_with_cluster_size_3_plus():
    seen = {"u1": 0, "u2": 0, "u3": 0}
    items = [
        {"id": 0, "title": "Story A", "link": "u1", "source": "CBC", "cluster_size": 4},
        {"id": 1, "title": "Story B", "link": "u2", "source": "BBC", "cluster_size": 2},
        {"id": 2, "title": "Story C", "link": "u3", "source": "NYT", "cluster_size": 1},
    ]
    result = monday_dedup_bypass(items, seen)
    assert {i["id"] for i in result} == {0}
