from app.services.oven_engine import (
    Interval,
    Occupancy,
    RecipeDurations,
    build_occupancies,
    find_conflicts,
    first_reschedule_conflict,
    next_free_window,
)


def test_half_open_no_touch_conflict():
    a = Occupancy(1, Interval(0, 30), "bake", 1)
    b = Occupancy(1, Interval(30, 60), "bake", 2)
    assert find_conflicts([a], [b]) == []


def test_overlap_detected():
    recipe = RecipeDurations(20, 30)
    cand = build_occupancies(1, 9, 10, recipe)
    existing = [Occupancy(1, Interval(25, 40), "bake", 1)]
    assert find_conflicts(existing, cand)


def test_next_free_window_after_busy():
    existing = [
        Occupancy(1, Interval(0, 40), "ferment", 1),
        Occupancy(1, Interval(40, 70), "bake", 1),
    ]
    w = next_free_window(existing, 1, duration=30, search_from=0)
    assert w == Interval(70, 100)


def test_next_free_in_gap():
    existing = [
        Occupancy(1, Interval(0, 20), "bake", 1),
        Occupancy(1, Interval(80, 100), "bake", 2),
    ]
    w = next_free_window(existing, 1, duration=30, search_from=0)
    assert w == Interval(20, 50)


def test_reschedule_conflict_with_existing():
    # 既有占用 [630,660)，重算候选 [600,645) 与之重叠
    existing = [Occupancy(2, Interval(630, 660), "ferment", 2)]
    groups = [build_occupancies(2, 1, 600, RecipeDurations(0, 45))]
    hit = first_reschedule_conflict(existing, groups)
    assert hit is not None
    ex, cand = hit
    assert ex.batch_id == 2 and cand.batch_id == 1


def test_reschedule_no_conflict_when_gap():
    existing = [Occupancy(2, Interval(640, 680), "ferment", 2)]
    groups = [build_occupancies(2, 1, 600, RecipeDurations(0, 35))]
    assert first_reschedule_conflict(existing, groups) is None


def test_reschedule_candidates_conflict_with_each_other():
    # 同产品同炉两批次同时按新时长重算：第一炉延长后撞上第二炉
    groups = [
        build_occupancies(1, 1, 600, RecipeDurations(0, 90)),
        build_occupancies(1, 2, 660, RecipeDurations(0, 90)),
    ]
    hit = first_reschedule_conflict([], groups)
    assert hit is not None
    ex, cand = hit
    assert {ex.batch_id, cand.batch_id} == {1, 2}


def test_reschedule_ignores_other_ovens():
    existing = [Occupancy(1, Interval(600, 700), "bake", 9)]
    groups = [build_occupancies(2, 1, 600, RecipeDurations(0, 90))]
    assert first_reschedule_conflict(existing, groups) is None
