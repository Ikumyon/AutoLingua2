from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
import math

from autolingua2_native import classification as native

from autolingua2.adapters.base import FileAdapter
from autolingua2.infrastructure.operations import check_cancelled, report_progress
from autolingua2.ir.classification import (
    ClassificationResult, ClassifiedElement, DifferenceKind, SourceCategory, SourceGroup, TextDifference,
)
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.unit import TranslationUnit
from autolingua2.ir.filter_rules import AdapterFilterConfig, TagRules
from autolingua2.services.filter_rules import get_filter_config


_COMPARISON_BATCH = 128


@dataclass(slots=True)
class _Cluster:
    members: list[int]
    radius: int
    min_length: int


def _comparison_texts(units: list[TranslationUnit], rules: TagRules) -> tuple[list[str], set[str]]:
    result: list[str] = []
    excluded: set[str] = set()
    for start in range(0, len(units), 1024):
        check_cancelled()
        for unit in units[start:start + 1024]:
            check_cancelled()
            comparison, hidden = rules.analyze(unit.source_text)
            result.append(comparison)
            if hidden:
                excluded.add(unit.id)
    return result, excluded


def _similarity(a: str, b: str, edits: int) -> Fraction:
    length = max(len(a), len(b))
    return Fraction(length - edits, length) if length else Fraction(1)


def _similar_groups(texts: list[str], remaining: set[int], threshold: Fraction) -> list[list[int]]:
    clusters: list[_Cluster] = []
    index = native.DistanceIndex()
    max_representative_length = 0
    numerator, denominator = threshold.numerator, threshold.denominator

    def allowed(a_length: int, b_length: int) -> int:
        return (denominator - numerator) * max(a_length, b_length) // denominator

    for position, unit_index in enumerate(sorted(remaining)):
        check_cancelled()
        value = texts[unit_index]
        if not value:
            continue
        if position % 128 == 0:
            report_progress(f"類似文を分類しています… {position} / {len(remaining)}")
        # Any qualifying representative has length <= len(value) / threshold.
        radius = min(
            (denominator - numerator) * len(value) // numerator,
            max(len(value), max_representative_length),
        )
        candidates: list[tuple[int, int, dict[int, int]]] = []
        for cluster_index, representative_distance in sorted(index.query(value, radius, check_cancelled)):
            check_cancelled()
            cluster = clusters[cluster_index]
            representative_index = cluster.members[0]
            if representative_distance > allowed(len(value), len(texts[representative_index])):
                continue
            known = {representative_index: representative_distance}
            # A sufficient bound for every pair, accounting for different text lengths.
            guaranteed = representative_distance + cluster.radius <= allowed(len(value), cluster.min_length)
            if not guaranteed:
                guaranteed = True
                members_to_check = cluster.members[1:]
                for start in range(0, len(members_to_check), _COMPARISON_BATCH):
                    check_cancelled()
                    batch = members_to_check[start:start + _COMPARISON_BATCH]
                    comparisons = native.distances(value, [
                        (texts[member], allowed(len(value), len(texts[member]))) for member in batch
                    ], check_cancelled)
                    for member, edits in zip(batch, comparisons, strict=True):
                        if edits is None:
                            guaranteed = False
                            break
                        known[member] = edits
                    if not guaranteed:
                        break
            if guaranteed:
                candidates.append((cluster_index, representative_distance, known))

        chosen: tuple[int, int, dict[int, int]] | None = None
        if len(candidates) == 1:
            # Membership is proven; no pairwise scores are needed to choose a group.
            chosen = candidates[0]
        elif candidates:
            best_score = Fraction(-1)
            for candidate in candidates:
                cluster_index, _, known = candidate
                score = Fraction(1)
                members = clusters[cluster_index].members
                for start in range(0, len(members), _COMPARISON_BATCH):
                    check_cancelled()
                    batch = members[start:start + _COMPARISON_BATCH]
                    missing = [member for member in batch if member not in known]
                    comparisons = native.distances(value, [(texts[member], None) for member in missing], check_cancelled)
                    for member, edits in zip(missing, comparisons, strict=True):
                        if edits is None:
                            raise RuntimeError("上限なしの編集距離が取得できませんでした。")
                        known[member] = edits
                    for member in batch:
                        score = min(score, _similarity(value, texts[member], known[member]))
                        if score <= best_score:
                            break
                    if score <= best_score:
                        break
                if score > best_score:
                    chosen = candidate
                    best_score = score
        if chosen is None:
            cluster_index = len(clusters)
            index.add(value, cluster_index, check_cancelled)
            clusters.append(_Cluster([unit_index], 0, len(value)))
            max_representative_length = max(max_representative_length, len(value))
        else:
            cluster_index, representative_distance, _ = chosen
            cluster = clusters[cluster_index]
            cluster.members.append(unit_index)
            cluster.radius = max(cluster.radius, representative_distance)
            cluster.min_length = min(cluster.min_length, len(value))
    return [cluster.members for cluster in clusters if len(cluster.members) >= 2]


def classify_sources(
    imported: ImportedTranslation, adapter: FileAdapter, *, threshold: float = 0.8,
    config: AdapterFilterConfig | None = None,
) -> ClassificationResult:
    """Classify all source units and publish only the completed, cancellable result."""
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("類似度の閾値は0より大きく1以下にしてください。")
    check_cancelled()
    rules = TagRules(config if config is not None else get_filter_config(adapter, imported.project.game_id))
    units = sorted(imported.project.units, key=lambda unit: unit.id)
    if len({unit.id for unit in units}) != len(units):
        raise ValueError("翻訳項目IDが重複しています。")
    remaining = set(range(len(units)))
    memberships: list[tuple[SourceCategory, list[int]]] = []
    report_progress("完全一致の原文を分類しています…")
    exact: dict[str, list[int]] = defaultdict(list)
    for unit_index, unit in enumerate(units):
        check_cancelled()
        exact[unit.source_text].append(unit_index)
    for members in exact.values():
        check_cancelled()
        if len(members) >= 2:
            memberships.append((SourceCategory.EXACT, members))
            remaining.difference_update(members)

    report_progress("非言語文字列の違いを分類しています…")
    texts, excluded = _comparison_texts(units, rules)
    normalized: dict[str, list[int]] = defaultdict(list)
    for unit_index in sorted(remaining):
        check_cancelled()
        if texts[unit_index]:
            normalized[texts[unit_index]].append(unit_index)
    for members in normalized.values():
        check_cancelled()
        if len(members) >= 2:
            memberships.append((SourceCategory.NON_LANGUAGE, members))
            remaining.difference_update(members)

    for members in _similar_groups(texts, remaining, Fraction(str(threshold))):
        memberships.append((SourceCategory.SIMILAR, members))
        remaining.difference_update(members)
    memberships.extend((SourceCategory.OTHER, [unit_index]) for unit_index in sorted(remaining))

    order = {category: position for position, category in enumerate(SourceCategory)}
    memberships.sort(key=lambda item: (order[item[0]], item[1][0]))
    counts: dict[SourceCategory, int] = defaultdict(int)
    groups: list[SourceGroup] = []
    report_progress("集合体の差分を記録しています…")
    for category, members in memberships:
        check_cancelled()
        counts[category] += 1
        representative_index = members[0]
        representative = units[representative_index]
        elements: list[ClassifiedElement] = []
        for start in range(0, len(members), _COMPARISON_BATCH):
            check_cancelled()
            batch = members[start:start + _COMPARISON_BATCH]
            changed = [member for member in batch if units[member].source_text != representative.source_text]
            analyses = iter(native.analyze_batch(
                representative.source_text, texts[representative_index],
                [(units[member].source_text, texts[member]) for member in changed], check_cancelled,
            ) if changed else [])
            for member in batch:
                check_cancelled()
                unit = units[member]
                spans: list[tuple[str, int, int, int, int]]
                if unit.source_text == representative.source_text:
                    edits, spans = 0, []
                else:
                    edits, spans = next(analyses)
                differences = tuple(
                    TextDifference(
                        DifferenceKind(kind), source_start, end, target_start, target_end,
                        representative.source_text[source_start:end], unit.source_text[target_start:target_end],
                    )
                    for kind, source_start, end, target_start, target_end in spans
                )
                elements.append(ClassifiedElement(
                    unit.id, edits, float(_similarity(texts[representative_index], texts[member], edits)), differences,
                ))
        groups.append(SourceGroup(
            f"{'ABCD'[order[category]]}-{counts[category]:03d}", category, representative.id, tuple(elements),
        ))
    result = ClassificationResult(threshold, tuple(groups))
    check_cancelled()
    imported.classification = result
    imported.excluded_unit_ids.clear()
    imported.excluded_unit_ids.update(excluded)
    return result
