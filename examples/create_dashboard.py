"""Создать обновлённый dashboard.html из сохранённых результатов BlocksNet.

Положите этот файл в examples/create_dashboard.py проекта.
Запуск из корня проекта: .venv/bin/python examples/create_dashboard.py
Никаких новых запросов к OSM, перерасчётов ноутбука или внешних JS-библиотек.
"""
from __future__ import annotations

import csv
import base64
import hashlib
import html
import json
import math
from collections import Counter
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

from shapely.geometry import shape

# Пути работают независимо от текущей рабочей директории терминала.
EXAMPLES_DIR = Path(__file__).resolve().parent
DATA_DIR = EXAMPLES_DIR / "data" / "lodeynoye_pole"
RESULTS_DIR = DATA_DIR / "results"
OUTPUT_FILE = RESULTS_DIR / "dashboard.html"
INPUT_FILE = RESULTS_DIR / "blocks_metrics.geojson"

# Названия и единицы — для диаграмм, фильтров, карт и таблиц.
LABELS = {
    'block_id': 'ID квартала', 'land_use':'Землепользование', 'strelka_morphotype':'Морфотип Strelka',
    'spacematrix_morphotype':'Морфотип Spacematrix', 'spacematrix_cluster':'Кластер Spacematrix',
    'spacematrix_status':'Статус Spacematrix', 'area_accessibility':'Среднее модельное время',
    'reachable_area_share':'Доля достижимой площади', 'unreachable_destinations':'Недоступных кварталов',
    'has_unreachable_destinations':'Есть недоступные назначения',
    'fsi':'FSI · интенсивность застройки', 'gsi':'GSI · доля застройки',
    'mxi':'MXI · доля жилой поэтажной площади', 'osr':'OSR · открытая территория / поэтажная площадь',
    'l':'Средняя этажность', 'site_area':'Площадь квартала',
    'footprint_area':'Площадь пятна зданий','build_floor_area':'Поэтажная площадь',
    'living_area':'Жилая площадь', 'non_living_area':'Нежилая площадь',
    'building_count':'Число зданий', 'population':'Модельное население',
    'school_count':'Школьных объектов', 'capacity':'Модельная вместимость школ',
    'demand':'Модельный спрос на места','demand_left':'Необеспеченный спрос',
    'demand_within':'Спрос, обеспеченный в пороге', 'demand_without':'Спрос, обеспеченный вне порога',
    'capacity_left':'Остаток вместимости','capacity_within':'Вместимость в пороге','capacity_without':'Вместимость вне порога',
    'provision_strong':'Обеспеченность школами (в пороге)',
    'provision_weak':'Обеспеченность школами (расширенная)',
    'agriculture':'Сельскохозяйственная функция','business':'Деловая функция',
    'industrial':'Промышленная функция','recreation':'Рекреационная функция',
    'residential':'Жилая функция','special':'Специальная функция',
    'transport':'Транспортная функция','share':'Доля ведущей функции',
    'share_living':'Жилая площадь / пятно','share_non_living':'Нежилая площадь / пятно',
    'population_source':'Источник населения','travel_mode':'Вид транспорта',
    'travel_time_unit':'Единица времени','snap_distance_m':'Длина привязки к дороге',
    'long_snap':'Превышение длины привязки', 'node_id':'Узел дорожного графа'
}
UNITS = {'area_accessibility':'мин','fsi':'м²/м²','gsi':'доля','mxi':'доля','osr':'м²/м²',
         'site_area':'м²','footprint_area':'м²','build_floor_area':'м²','living_area':'м²',
         'non_living_area':'м²','population':'чел. (оценка)','capacity':'мест (оценка)',
         'demand':'мест (оценка)','provision_strong':'доля','provision_weak':'доля',
         'reachable_area_share':'доля','school_count':'объектов','building_count':'зданий',
         'l':'этажа','share_living':'м²/м²','share_non_living':'м²/м²',
         'share':'доля','residential':'доля','business':'доля','industrial':'доля',
         'recreation':'доля','special':'доля','transport':'доля','agriculture':'доля',
         'snap_distance_m':'м', 'demand_left':'мест (оценка)', 'demand_within':'мест (оценка)',
         'demand_without':'мест (оценка)', 'capacity_left':'мест (оценка)',
         'capacity_within':'мест (оценка)', 'capacity_without':'мест (оценка)'}
LAND_NAMES = {'residential':'Жилое','industrial':'Промышленное','recreation':'Рекреационное',
              'special':'Специальное','business':'Деловое','transport':'Транспортное',
              'agriculture':'Сельскохозяйственное', None:'Не определено'}
MORPH_NAMES = {'low-rise non-residential':'Малоэтажная нежилая',
               'low-rise model':'Малоэтажная модельная',
               'mid-rise':'Среднеэтажная','individual residential':'Индивидуальная жилая',
               'low-rise low-density non-residential':'Малоэтажная нежилая низкой плотности',
               'low-rise low-density residential':'Малоэтажная жилая низкой плотности',
               'low-rise low-density mixed-use':'Малоэтажная смешанная низкой плотности',
               'mid-rise low-density residential':'Среднеэтажная жилая низкой плотности',
               'mid-rise residential':'Среднеэтажная жилая',
               None:'Не определён'}


CORE_METRICS = (
    'fsi', 'gsi', 'mxi', 'l', 'osr', 'share_living', 'share_non_living',
    'spacematrix_morphotype', 'strelka_morphotype',
    'provision_strong', 'provision_weak', 'area_accessibility',
)
NUMERIC_METRICS = tuple(key for key in CORE_METRICS if not key.endswith('_morphotype'))
LAND_USE_COLUMNS = ('residential', 'business', 'recreation', 'industrial', 'transport',
                    'special', 'agriculture', 'share')
ANCHOR_COLUMNS = ('node_id', 'snap_distance_m', 'long_snap')


def read_json(path: Path) -> Any:
    """Read a local JSON file without substituting missing data."""
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read saved CSV headers and records."""
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def same_value(left: Any, right: Any) -> bool:
    """Compare serialized values, retaining the distinction between zero and null."""
    if left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (float, int)) and isinstance(right, (float, int)):
        return math.isclose(left, right, rel_tol=1e-8, abs_tol=1e-6)
    return left == right


def load_results() -> list[dict[str, Any]]:
    """Читаем готовый GeoJSON, не обращаясь к интернету или ноутбуку."""
    if not INPUT_FILE.is_file():
        raise FileNotFoundError(
            f"Не найден {INPUT_FILE}. Сначала сохраните results/blocks_metrics.geojson из ноутбука."
        )
    with INPUT_FILE.open(encoding="utf-8") as stream:
        source = json.load(stream)
    if source.get("type") != "FeatureCollection":
        raise ValueError("blocks_metrics.geojson должен быть GeoJSON FeatureCollection")
    features = source.get("features", [])
    if not features:
        raise ValueError("В blocks_metrics.geojson нет кварталов")

    # GeoJSON — единственный источник значений. CSV служат для сверки,
    # а не для незаметного заполнения null из другого снимка расчёта.
    by_feature_id = {}
    for feature in features:
        props = feature.get("properties") or {}
        bid = normalise_id(props.get("block_id"))
        if bid is None or bid in by_feature_id:
            raise ValueError("В GeoJSON отсутствует или повторяется block_id")
        missing = set(CORE_METRICS) - props.keys()
        if missing:
            raise ValueError(f"Квартал {bid}: отсутствуют показатели {sorted(missing)}. Выполните раздел 11.")
        by_feature_id[bid] = props
    for name in ("blocks_metrics.csv", "density_blocks.csv", "morphotypes_blocks.csv",
                 "provision_blocks.csv", "accessibility_blocks.csv"):
        path = RESULTS_DIR / name
        headers, records = read_csv_rows(path)
        # a9 теряет имя индекса после валидации; старые файлы используют row_id.
        id_field = "block_id" if "block_id" in headers else "row_id"
        if id_field not in headers:
            raise ValueError(f"{name}: нет block_id или row_id")
        by_id = {}
        for record in records:
            bid = normalise_id(record.get(id_field))
            if bid is None or bid in by_id:
                raise ValueError(f"{name}: отсутствующий или повторный ID {bid}")
            by_id[bid] = record
        if set(by_id) != set(by_feature_id):
            raise ValueError(f"{name}: набор кварталов отличается от GeoJSON. Повторите разделы 11–13.")
        for bid, record in by_id.items():
            props = by_feature_id[bid]
            for key, value in record.items():
                if key == id_field:
                    continue
                # Числовой текст node_id остаётся строкой, как в исходном GeoJSON.
                parsed = value if isinstance(props.get(key), str) else parse_csv_value(value)
                if key not in props or not same_value(props[key], parsed):
                    raise ValueError(f"{name}: квартал {bid}, поле {key} расходится с GeoJSON. Повторите раздел 11.")
    return features


def normalise_id(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
        return str(int(number)) if number.is_integer() else str(value).strip()
    except (TypeError, ValueError):
        return str(value).strip()


def parse_csv_value(value: str | None) -> Any:
    if value is None or value.strip().lower() in ("", "none", "null", "nan"):
        return None
    try:
        v = float(value)
        if math.isfinite(v):
            return int(v) if v.is_integer() else v
        return None
    except ValueError:
        pass
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    return value


def polygon_rings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    """Возвращаем все кольца Polygon и MultiPolygon, включая отверстия."""
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [ring for ring in coords if ring]
    if kind == "MultiPolygon":
        return [ring for polygon in coords for ring in polygon if ring]
    return []


def audit_results(features: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    """Check saved formulas, balances, travel weights and provenance; never solve or download."""
    props = {normalise_id(f['properties']['block_id']): f['properties'] for f in features}

    def check(actual: Any, expected: Any, context: str) -> None:
        if not same_value(actual, expected):
            raise ValueError(f"Сверка: {context}: {actual!r} != {expected!r}. Обновите зависимые ячейки.")

    def ratio(a: float, b: float) -> float | None:
        return a / b if b > 0 else None

    for bid, p in props.items():
        area, footprint, floor = p['site_area'], p['footprint_area'], p['build_floor_area']
        if area <= 0:
            raise ValueError(f"Квартал {bid}: неположительная площадь")
        expected = {
            'fsi': floor / area, 'gsi': min(1, max(0, footprint / area)),
            'mxi': min(1, max(0, p['living_area'] / floor)) if floor > 0 else None,
            'l': max(1, floor / footprint) if footprint > 0 else None,
            'osr': ratio(area - footprint, floor),
            'share_living': ratio(p['living_area'], footprint),
            'share_non_living': ratio(p['non_living_area'], footprint),
        }
        for key, value in expected.items():
            check(p[key], value, f"квартал {bid}, {key}")
        check(p['demand'], math.ceil(p['population'] / 1000 * summary['assumptions']['school_demand_per_1000']),
              f'{bid}: спрос с округлением вверх')
        check(p['demand'], p['demand_left'] + p['demand_within'] + p['demand_without'], f"{bid}: спрос")
        own = min(p['demand'], p['capacity']) if summary['assumptions']['provision_self_supply'] else 0
        check(p['capacity'], p['capacity_left'] + p['capacity_within'] + p['capacity_without'] + own,
              f"{bid}: вместимость с самообеспечением")
        check(p['provision_strong'], ratio(p['demand_within'], p['demand']), f"{bid}: strong")
        check(p['provision_weak'], ratio(p['demand_within'] + p['demand_without'], p['demand']), f"{bid}: weak")

    check(summary['blocks'], len(props), 'число кварталов в summary.json')
    for field, total_field in [('population', 'model_population'), ('capacity', 'model_school_capacity'),
                               ('demand', 'school_demand'), ('school_count', 'schools')]:
        check(summary[total_field], sum(p[field] for p in props.values()), total_field)
    total_demand = sum(p['demand'] for p in props.values())
    within = sum(p['demand_within'] for p in props.values())
    without = sum(p['demand_without'] for p in props.values())
    check(summary['city_provision_strong'], ratio(within, total_demand), 'городской strong')
    check(summary['city_provision_weak'], ratio(within + without, total_demand), 'городской weak')

    matrix_path = RESULTS_DIR / 'travel_minutes.csv'
    headers, rows = read_csv_rows(matrix_path)
    targets = [normalise_id(key) for key in headers[1:]]
    origins = [normalise_id(row[headers[0]]) for row in rows]
    if len(set(targets)) != len(targets) or len(set(origins)) != len(origins):
        raise ValueError('Матрица времени содержит повторные ID')
    if set(targets) != set(props) or set(origins) != set(props):
        raise ValueError('Матрица времени относится к другому набору кварталов')
    total_area = sum(p['site_area'] for p in props.values())
    unreachable_pairs = 0
    for row, bid in zip(rows, origins):
        times = [float(row[key]) for key in headers[1:]]
        if any(math.isnan(t) or t < 0 for t in times):
            raise ValueError(f'Матрица: некорректное время из {bid}')
        check(times[targets.index(bid)], 0, f'диагональ матрицы {bid}')
        unreachable = sum(not math.isfinite(t) for t in times)
        unreachable_pairs += unreachable
        weighted = None if unreachable else sum(t * props[target]['site_area']
                                               for t, target in zip(times, targets)) / total_area
        check(props[bid]['area_accessibility'], weighted, f'{bid}: площадная доступность')
        check(props[bid]['unreachable_destinations'], unreachable, f'{bid}: недоступные назначения')
        check(props[bid]['has_unreachable_destinations'], bool(unreachable), f'{bid}: признак недоступности')
        reachable = sum(props[target]['site_area'] for t, target in zip(times, targets) if math.isfinite(t))
        check(props[bid]['reachable_area_share'], reachable / total_area, f'{bid}: достижимая площадь')
    check(summary['unreachable_pairs'], unreachable_pairs, 'недоступные пары в summary.json')

    # Подготовленный список школ и дополнительные поля должны относиться к той же модели.
    model_meta = read_json(DATA_DIR / 'prepared/block_model.geojson.meta.json')
    for name in ('blocks', 'land_use', 'buildings', 'schools'):
        path = DATA_DIR / 'prepared' / f'{name}.geojson'
        check(hashlib.sha256(path.read_bytes()).hexdigest(), model_meta['parameters'][name],
              f'исходный слой модели {name}; повторите раздел 4.4 и зависимые разделы')
    for filename, fields in [('land_use.geojson', ('land_use', *LAND_USE_COLUMNS)),
                             ('block_anchors.geojson', ANCHOR_COLUMNS)]:
        source = {}
        for feature in read_json(DATA_DIR / 'prepared' / filename)['features']:
            p = feature['properties']
            bid = normalise_id(p['block_id'])
            if bid is None or bid in source:
                raise ValueError(f'{filename}: отсутствующий или повторный ID')
            source[bid] = p
        check(set(source), set(props), f'{filename}: набор ID')
        for bid, p in props.items():
            for field in fields:
                if field in p:
                    check(p[field], source[bid][field], f'{filename}, {bid}, {field}')
    schools = [f['properties'] for f in read_json(DATA_DIR / 'prepared/schools.geojson')['features']]
    check(summary['schools'], len(schools), 'число объектов в списке школ')
    school_meta = read_json(DATA_DIR / 'prepared/schools.geojson.meta.json')
    if 'school_excluded_osm_ids' in summary['assumptions']:
        excluded = summary['assumptions']['school_excluded_osm_ids']
        check(excluded, school_meta['parameters'].get('excluded_osm_ids', {}), 'сценарий исключения школ')
        for school in schools:
            if str(school.get('osm_id')) in excluded:
                raise ValueError('В подготовленном списке осталась исключённая школа. Повторите раздел 4.3.')
    travel_meta = read_json(RESULTS_DIR / 'travel.meta.json')
    check(summary['matrix_parameters'], travel_meta['parameters'], 'паспорт матрицы времени')
    check(summary['graph']['sha256'], travel_meta['parameters']['graph'], 'граф в паспорте')

    # Проверяем входные контрольные суммы только для действительно использованных артефактов.
    for group in ('density', 'morphotypes', 'provision', 'accessibility', 'travel'):
        meta = read_json(RESULTS_DIR / f'{group}.meta.json')
        for name, filename in meta['files'].items():
            digest = hashlib.sha256((RESULTS_DIR / filename).read_bytes()).hexdigest()
            check(digest, meta['sha256'][name], f'{group}: контрольная сумма {filename}')
        inputs = {'model': DATA_DIR / 'prepared/block_model.geojson',
                  'matrix': matrix_path, 'density': RESULTS_DIR / 'density_blocks.csv',
                  'blocks': DATA_DIR / 'prepared/blocks.geojson',
                  'anchors': DATA_DIR / 'prepared/block_anchors.geojson',
                  'graph': DATA_DIR / 'graph/drive.graphml'}
        for key, path in inputs.items():
            if key in meta['parameters']:
                check(hashlib.sha256(path.read_bytes()).hexdigest(), meta['parameters'][key],
                      f'{group}: входной файл {path.name}')

    # Сверка сводных таблиц с теми же значениями, которые попадут на карту.
    _, rows = read_csv_rows(RESULTS_DIR / 'descriptive_statistics.csv')
    if len(rows) != len(NUMERIC_METRICS) or {row['metric'] for row in rows} != set(NUMERIC_METRICS):
        raise ValueError('Неполная таблица статистик. Повторите раздел 11.1.')
    for row in rows:
        key = row['metric']
        values = sorted(p[key] for p in props.values() if isinstance(p[key], (int, float))
                        and not isinstance(p[key], bool) and math.isfinite(p[key]))

        def quantile(fraction: float) -> float | None:
            if not values:
                return None
            position = (len(values) - 1) * fraction
            lo, hi = math.floor(position), math.ceil(position)
            return values[lo] + (values[hi] - values[lo]) * (position - lo)

        expected = {'count': len(values), 'missing': len(props) - len(values),
                    'mean': fmean(values) if values else None,
                    'std': stdev(values) if len(values) > 1 else None,
                    'min': values[0] if values else None, 'max': values[-1] if values else None,
                    '25%': quantile(.25), '50%': quantile(.5), '75%': quantile(.75)}
        for stat, value in expected.items():
            check(parse_csv_value(row[stat]), value, f'статистики {key}, {stat}; повторите раздел 11.1')
    for key in ('spacematrix_morphotype', 'strelka_morphotype'):
        _, rows = read_csv_rows(RESULTS_DIR / f'{key}_counts.csv')
        saved = {row['morphotype']: int(row['blocks']) for row in rows}
        expected = dict(Counter(p[key] or 'не определён' for p in props.values()))
        check(saved, expected, f'частоты {key}; повторите раздел 11.1')


def saved_tables_html(summary: dict[str, Any], features: list[dict[str, Any]]) -> str:
    """Embed the saved ancillary tables and their CSV downloads in the single HTML file."""
    parts = []
    for filename, title in [
        ('descriptive_statistics.csv', 'Описательные статистики · раздел 11.1'),
        ('morphotypes_clusters.csv', 'Центры Spacematrix (медианы) · раздел 6'),
        ('spacematrix_morphotype_counts.csv', 'Частоты морфотипов Spacematrix · раздел 11.1'),
        ('strelka_morphotype_counts.csv', 'Частоты морфотипов Strelka · раздел 11.1'),
        ('provision_links.csv', 'Распределение школьных мест между кварталами · раздел 9'),
        ('travel_minutes.csv', 'Матрица времени, минуты · раздел 8'),
        ('quality_checks.csv', 'Все проверки качества · раздел 12'),
        ('route_checks.csv', 'Ручные проверки маршрутов · раздел 12.1'),
    ]:
        path = RESULTS_DIR / filename
        if not path.is_file():
            parts.append(f'<p>{html.escape(title)}: файл ещё не сохранён.</p>')
            continue
        encoded = base64.b64encode(path.read_bytes()).decode('ascii')
        headers, rows = read_csv_rows(path)
        parts.append(f'<details class="card chart-card"><summary>{html.escape(title)} · строк: {len(rows)}</summary>')
        parts.append(f'<p><a download="{filename}" href="data:text/csv;base64,{encoded}">Скачать {filename}</a></p>')
        if filename != 'travel_minutes.csv':
            parts.append('<div class="table-scroll"><table><thead><tr>' + ''.join(
                f'<th>{html.escape(label)}</th>' for label in headers) + '</tr></thead><tbody>')
            for row in rows:
                parts.append('<tr>' + ''.join(f'<td>{html.escape(row.get(key) or "—")}</td>' for key in headers) + '</tr>')
            parts.append('</tbody></table></div>')
        else:
            parts.append('<p>Строка — отправление, столбец — назначение. inf — пути нет; 0 на диагонали.</p>')
        parts.append('</details>')
    fields = ('block_id', 'population', 'demand', 'capacity', 'demand_left', 'provision_strong')
    deficit = sorted((f['properties'] for f in features), key=lambda p: p['demand_left'], reverse=True)[:15]
    parts.append('<details class="card chart-card"><summary>Крупнейший необеспеченный спрос · раздел 11.1</summary>')
    parts.append('<p>15 кварталов по убыванию demand_left; при равенстве порядок может отличаться от pandas.</p>')
    parts.append('<div class="table-scroll"><table><thead><tr>' + ''.join(
        f'<th>{html.escape(LABELS.get(key, key))}</th>' for key in fields) + '</tr></thead><tbody>')
    for p in deficit:
        parts.append('<tr>' + ''.join(
            f'<td>{html.escape(str(p[key])) if p[key] is not None else "—"}</td>' for key in fields) + '</tr>')
    parts.append('</tbody></table></div></details>')
    notes = summary.get('observations') or []
    parts.append('<article class="card chart-card"><h3>Выводы · раздел 13</h3>' + (
        '<ul>' + ''.join(f'<li>{html.escape(str(note))}</li>' for note in notes) + '</ul>'
        if notes else '<p>Выводы в summary.json ещё не заполнены.</p>') + '</article>')
    parts.append('<article class="card chart-card"><h3>Паспорт расчёта и параметры</h3><pre style="white-space:pre-wrap">' +
                 html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + '</pre></article>')
    return '\n'.join(parts)


def school_details_html() -> str:
    """Display the saved school list and imputed capacities."""
    path = DATA_DIR / 'prepared/schools.geojson'
    if not path.is_file():
        return '<p>Сохранённый список школ отсутствует.</p>'
    schools = [f['properties'] for f in read_json(path)['features']]
    imputed = sum(p.get('capacity_imputed') is True for p in schools)
    parts = [f'<p>Школ с восстановленной вместимостью: {imputed} из {len(schools)}.</p>', '<ul>']
    for p in schools:
        name = p.get('name') or f"Без названия, OSM {p.get('osm_id', '—')}"
        parts.append(f'<li>{html.escape(str(name))}: {html.escape(str(p.get("capacity", "—")))} мест</li>')
    parts.append('</ul>')
    return ''.join(parts)


def method_html(summary: dict[str, Any]) -> str:
    """Describe the source recorded in the passport instead of hard-coded conclusions."""
    graph = summary.get('graph', {})
    date = graph.get('source_date', 'неизвестна')
    created = graph.get('graph_created_at', 'не записана')
    if graph.get('graph_created_with') == 'OSMnx' and 'graph_created_at' not in graph:
        created = graph.get('source_date', 'не записана')
        date = 'не подтверждена (source_date старого паспорта обозначал дату создания графа)'
    rows = [
        ('Версия BlocksNet', summary.get('software', {}).get('blocksnet', 'не указана')),
        ('Источник графа', graph.get('source_page', 'не указан')),
        ('Метод времени', graph.get('time_method', 'не указан')),
        ('Поле и единица исходного времени', f"{graph.get('source_time_attribute')} / {graph.get('source_time_unit')}"),
        ('Дата создания / получения графа', created), ('Дата снимка OSM', date),
        ('Проверено маршрутов вручную', summary.get('manual_route_pairs_checked', 0)),
    ]
    return ('<article class="card method-card"><h3>Источники и допущения</h3>'
            '<p>Часть характеристик зданий и вместимость школ оценены по допущениям модели. '
            'Результаты предназначены для учебного сравнения кварталов.</p><ul>' + ''.join(
        f'<li>{html.escape(key)}: {html.escape(str(value))}</li>' for key, value in rows
    ) + '</ul><p>Площадная доступность = Σ(время из квартала × площадь назначения) / Σ(площадь назначения). '
        'Меньше минут означает меньшие затраты времени; это не среднее по жителям. '
        'Недостижимые назначения дают неопределённое конечное время и отдельные признаки недоступности.</p>'
        '<p>Население и вместимость могут быть восстановлены оценочно. Неизвестное назначение здания '
        'не означает доказанное отсутствие жителей. OSR не измеряет озеленение; MXI — доля жилой площади. '
        'share_living и share_non_living делятся на пятно застройки и могут быть больше 1. '
        'Параметры и выводы приведены в паспорте выше.</p></article>')


def make_dataset(features: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    R = 6378137.0  # метры; проекция Меркатора исключительно для SVG-рисования
    coords: list[tuple[float, float]] = []
    for feature in features:
        for ring in polygon_rings(feature.get("geometry") or {}):
            for vertex in ring:
                lon, lat = vertex[:2]
                x = math.radians(lon) * R
                y = R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
                coords.append((x, y))
    if not coords:
        raise ValueError("В GeoJSON нет геометрий Polygon / MultiPolygon")
    minx, miny = min(p[0] for p in coords), min(p[1] for p in coords)
    maxx, maxy = max(p[0] for p in coords), max(p[1] for p in coords)
    W, H, padx, pady = 970, 590, 66, 50
    scale = min((W - 2 * padx) / max(maxx - minx, 1),
                (H - 2 * pady) / max(maxy - miny, 1))
    ox = (W - (maxx - minx) * scale) / 2
    oy = (H - (maxy - miny) * scale) / 2

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = math.radians(lon) * R
        y = R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        return ox + (x - minx) * scale, H - (oy + (y - miny) * scale)

    rows = []
    for feature in features:
        props = feature.get("properties") or {}
        rings = polygon_rings(feature.get("geometry") or {})
        parts = []
        vertices = []
        for ring in rings:
            converted = [project(float(vertex[0]), float(vertex[1])) for vertex in ring]
            if not converted:
                continue
            vertices.extend(converted)
            parts.append("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in converted) + " Z")
        if not parts:
            continue
        bid = normalise_id(props.get("block_id"))
        if bid is None:
            raise ValueError("В GeoJSON обнаружен квартал без block_id")
        rows.append({
            "id": int(bid),
            "d": " ".join(parts),
            "cx": round(sum(x for x, y in vertices) / len(vertices), 1),
            "cy": round(sum(y for x, y in vertices) / len(vertices), 1),
            "p": props,
        })
    rows.sort(key=lambda row: row["id"])
    if not rows:
        raise ValueError("В GeoJSON нет допустимых кварталов")
    ids = [row['id'] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('В GeoJSON повторяются значения block_id')

    # Одна точка на школу; среднее вершин квартала может попасть в соседний квартал.
    block_geometries = [(int(normalise_id(f['properties']['block_id'])), shape(f['geometry']))
                        for f in features]
    schools = []
    for index, feature in enumerate(read_json(DATA_DIR / 'prepared/schools.geojson')['features']):
        point = shape(feature['geometry']).representative_point()
        matches = [bid for bid, geometry in block_geometries if geometry.intersects(point)]
        props = feature.get('properties') or {}
        school_id = props.get('school_id') or f'school_{index}'
        if len(matches) != 1:
            raise ValueError(f'Школа {school_id}: не удалось однозначно определить квартал: {matches}')
        x, y = project(point.x, point.y)
        schools.append({
            'id': school_id, 'block_id': matches[0],
            'cx': round(x, 3), 'cy': round(y, 3),
            'name': props.get('name') or 'Школа без названия',
        })
    school_counts = Counter(school['block_id'] for school in schools)
    for row in rows:
        if school_counts[row['id']] != row['p']['school_count']:
            raise ValueError(f"Квартал {row['id']}: точки школ не совпадают с сохранённым school_count")

    land_count = Counter(row["p"].get("land_use") for row in rows)
    def numeric_values(key: str) -> list[float]:
        return [float(row["p"][key]) for row in rows
                if isinstance(row["p"].get(key), (float, int))
                and not isinstance(row["p"][key], bool)
                and math.isfinite(float(row["p"][key]))]

    fsi = numeric_values("fsi")
    gsi = numeric_values("gsi")
    times = numeric_values("area_accessibility")
    counts = {
        'total': len(rows), 'residential': land_count['residential'], 'missing': land_count[None],
        'land_use': {str(k):v for k,v in land_count.items()},
        'totalArea':sum(numeric_values('site_area')),
        'population':sum(numeric_values('population')),
        'capacity':sum(numeric_values('capacity')),
        'demand':sum(numeric_values('demand')),
        'schools':sum(numeric_values('school_count')),
        'avgFSI':sum(fsi)/len(fsi) if fsi else None,
        'avgGSI':sum(gsi)/len(gsi) if gsi else None,
        'avgTime':sum(times)/len(times) if times else None,
        'missingMorph':sum(row['p'].get('strelka_morphotype') is None for row in rows),
        'provisionCount':sum(row['p'].get('provision_strong') is not None for row in rows),
    }
    dictionary = read_json(RESULTS_DIR / 'metric_dictionary.json')
    labels, units = dict(LABELS), dict(UNITS)
    for key, entry in dictionary.items():
        labels[key] = entry['label']
        units[key] = entry['unit']
    return {'blocks': rows, 'schools': schools, 'labels': labels, 'units': units, 'summary': summary,
            'landNames': {str(k):v for k,v in LAND_NAMES.items()},
            'morphNames': {str(k):v for k,v in MORPH_NAMES.items()},
            'counts': counts}


TEMPLATE=r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Интерактивный атлас кварталов Лодейного Поля. Показатели BlocksNet, землепользование, морфотипы, доступность, школы.">
<title>Лодейное Поле — Атлас кварталов</title>
<style>
:root{--bg:#f5f5f1;--panel:#fff;--ink:#202f39;--ink2:#53616a;--quiet:#7d898e;--line:#e1e6e3;--deep:#162f38;--green:#366d67;--mint:#cfe6de;--tint:#e8f0ec;--orange:#b97755;--shadow:0 12px 32px #183a3210;--radius:17px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter, -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;font-size:14px;line-height:1.52}button,input,select{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid #79a99e;outline-offset:2px}
a{color:inherit} .max{max-width:1500px;margin:0 auto;padding:0 32px}
.top{background:#fff;border-bottom:1px solid var(--line)}.top-in{display:flex;align-items:center;justify-content:space-between;height:66px;gap:20px}.brand{display:flex;align-items:center;gap:10px;letter-spacing:.12em;font-size:12px;font-weight:800}.mark{width:35px;height:35px;display:grid;place-items:center;border-radius:10px;background:var(--deep);color:#fff;font-weight:750;font-size:16px;letter-spacing:0}.top-r{display:flex;align-items:center;gap:12px;color:var(--quiet);font-size:12px}.source-chip{border:1px solid #d9e5df;border-radius:50px;padding:6px 11px;background:#f8fbf9;color:#3d6960}
.hero{background:var(--deep);color:#fff;overflow:hidden;position:relative}.hero:after{content:"";position:absolute;width:450px;height:450px;border:1px solid #b0e4d01f;border-radius:50%;top:-120px;right:-50px;box-shadow:0 0 0 80px #b0e4d00c,0 0 0 160px #b0e4d00b;pointer-events:none}.hero-in{padding:55px 32px 50px;display:grid;grid-template-columns:1.55fr .8fr;gap:40px;align-items:center;position:relative;z-index:1}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.19em;font-weight:700;color:#b3cfc4}.hero h1{font-size:clamp(34px,4.1vw,59px);line-height:1.1;margin:17px 0 16px;letter-spacing:-.038em;font-weight:660}.hero p{max-width:650px;margin:0;font-size:16px;color:#d9e6e0;line-height:1.65}.hero-side{padding:23px;border:1px solid #bad4ca37;background:#fff0;border-radius:20px;backdrop-filter:blur(2px)}.hero-side span{font-size:12px;color:#bcd4cc}.hero-side strong{display:block;font-size:32px;letter-spacing:-.04em;margin:7px 0 12px;font-weight:700}.hero-meter{height:9px;display:flex;border-radius:6px;overflow:hidden;background:#637b80}.hero-meter>i{display:block;background:#81c6b7;width:65.6%}.hero-side small{display:block;color:#c9d9d6;line-height:1.5;margin-top:11px}.hero-side a{color:#bbdfd7}
.nav{position:sticky;top:0;z-index:40;background:#fffc;border-bottom:1px solid var(--line);backdrop-filter:blur(14px)}.nav-in{display:flex;gap:5px;overflow:auto;scrollbar-width:none}.nav a{padding:15px 17px;text-decoration:none;color:#64747b;font-weight:650;white-space:nowrap;font-size:13px}.nav a:hover,.nav a.active{color:#1b544d;background:#e7f0ec}
main{padding-top:34px;padding-bottom:70px}section{scroll-margin-top:85px;margin-bottom:54px}.section-top{display:flex;align-items:end;justify-content:space-between;gap:20px;margin:0 0 20px}.section-label{color:#3c8b7a;text-transform:uppercase;font-size:11px;font-weight:800;letter-spacing:.14em}.section-top h2{font-size:clamp(25px,2.4vw,33px);font-weight:680;letter-spacing:-.025em;line-height:1.17;margin:6px 0 0}.section-top p{color:var(--ink2);max-width:570px;margin:0}.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 2px 15px #203d3206}.stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.stat{padding:23px 23px 21px;min-width:0}.stat .sub{font-size:12px;color:var(--ink2);font-weight:650}.stat strong{display:block;margin-top:10px;font-size:clamp(25px,2.4vw,36px);line-height:1.2;font-weight:700;letter-spacing:-.04em;color:#163f40}.stat small{display:block;margin-top:10px;color:var(--quiet);font-size:11px}.info-grid{margin-top:16px;display:grid;grid-template-columns:1.15fr .85fr;gap:16px}.insight{padding:22px 25px}.insight h3{font-size:17px;margin:0 0 12px}.insight p{color:var(--ink2);margin:0;font-size:14px;line-height:1.7}.line-tag{display:inline-flex;border-radius:4px;padding:3px 7px;background:#e7f0ec;font-size:11px;font-weight:700;color:#38695f;margin-bottom:10px}.warning{background:#fff9f0;border:1px solid #f0dcc3}.warning .line-tag{background:#f6e6d4;color:#925d3e}
.atlas-card{overflow:hidden}.atlas-toolbar{display:flex;gap:15px;align-items:end;padding:18px 22px;border-bottom:1px solid var(--line);flex-wrap:wrap;background:#fff}.field{display:flex;flex-direction:column;gap:6px;min-width:180px;flex:1}.field.small{flex:.8;min-width:160px}.field label{font-size:11px;font-weight:750;color:#65777c;text-transform:uppercase;letter-spacing:.055em}select,input[type=search]{width:100%;min-height:39px;border-radius:9px;border:1px solid #d8e1dd;background:#fafcfb;padding:8px 11px;color:var(--ink);outline-color:#65a998;max-width:100%}.reset{padding:10px 14px;border:1px solid var(--line);background:#f6f8f7;border-radius:9px;font-size:12px;font-weight:700;color:#47746b;white-space:nowrap}.reset:hover{background:#e7efeb}.atlas-layout{display:grid;grid-template-columns:minmax(0,1fr) 340px}.map-shell{position:relative;background:radial-gradient(circle at 25% 30%,#f6faf8 1px,transparent 1.5px),#eaf1ed;background-size:24px 24px,auto;min-height:585px;overflow:hidden}.map-shell svg{width:100%;height:585px;display:block;touch-action:none;user-select:none}.geo{stroke:#fff;stroke-width:1;vector-effect:non-scaling-stroke;cursor:pointer;transition:opacity .13s,stroke .13s,stroke-width .13s}.geo:hover,.geo.focused{stroke:#233d43;stroke-width:2.3;vector-effect:non-scaling-stroke}.geo.dim{opacity:.09;pointer-events:none}.map-controls{position:absolute;right:20px;top:20px;display:flex;flex-direction:column;gap:5px}.map-btn{border-radius:9px;width:35px;height:35px;background:#fff;border:1px solid #dbe4e0;font-size:20px;color:#244e4a;box-shadow:0 3px 10px #102f2c16}.map-btn:hover{background:#edf5f1}.map-hint{position:absolute;left:17px;bottom:16px;background:#fffe;padding:7px 10px;border:1px solid #dce6e2;border-radius:8px;color:#6f8183;font-size:11px}.map-tip{position:absolute;pointer-events:none;display:none;z-index:3;border:1px solid #d5e3de;background:#fff;box-shadow:var(--shadow);border-radius:9px;padding:9px 12px;font-size:12px;max-width:230px;line-height:1.5}.map-side{background:#fff;border-left:1px solid var(--line);padding:22px;display:flex;flex-direction:column;gap:21px}.side-head{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:#73827e;font-weight:800;margin-bottom:9px}.legend-list{display:flex;flex-direction:column;gap:9px}.legend-item{display:flex;align-items:center;justify-content:space-between;gap:10px;color:#536168;font-size:12px}.legend-text{display:flex;align-items:center;gap:9px;min-width:0}.swatch{width:14px;height:14px;border-radius:3px;border:1px solid #0001;display:inline-block;flex:none}.legend-count{color:#90a099;font-variant-numeric:tabular-nums}.side-topline{display:flex;justify-content:space-between;gap:8px;align-items:start}.small-muted{font-size:12px;color:#81918c}.selected-title{font-size:22px;margin:0 0 12px;letter-spacing:-.03em}.side-data{display:grid;grid-template-columns:1fr auto;gap:10px 6px;font-size:12px}.side-data span{color:#74837c}.side-data strong{text-align:right;font-weight:750;color:#2e4548}.selected-note{background:#f0f5f2;border-radius:10px;padding:13px;color:#60716b;font-size:11px;line-height:1.6}.divider{height:1px;background:var(--line)}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}.chart-card{padding:25px}.chart-card h3{font-size:18px;letter-spacing:-.015em;margin:0 0 3px}.chart-caption{font-size:12px;color:#71827c;margin:0 0 24px}.bar-item{display:grid;grid-template-columns:minmax(0,175px) 1fr 47px;align-items:center;gap:11px;margin:13px 0}.bar-item label{font-size:12px;color:#49595e;line-height:1.25}.bar-track{height:12px;border-radius:5px;background:#edf1ef;overflow:hidden}.bar-fill{height:100%;border-radius:5px}.bar-number{font-variant-numeric:tabular-nums;text-align:right;color:#34464a;font-weight:750;font-size:12px}.chart-foot{color:#84918e;font-size:11px;margin-top:16px;padding-top:13px;border-top:1px solid var(--line)}.hist-svg{width:100%;height:auto;display:block}.hist-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;color:#526460;font-size:12px}.hist-title strong{color:#153d3d}.hist-range{display:flex;justify-content:space-between;color:#88948e;font-size:11px;margin-top:4px}.metric-note{font-size:12px;color:#667871;line-height:1.6}.access-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:16px}.toplist{display:grid;grid-template-columns:1fr 1fr;gap:10px}.topline{display:flex;justify-content:space-between;border-bottom:1px dashed #e0e9e5;padding:9px 0;gap:8px;font-size:12px}.topline span{color:#6b7b76}.topline strong{color:#285b55;font-variant-numeric:tabular-nums}.chart-bottom{margin-top:15px;font-size:12px;color:#74817e}
.school-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.comparison{padding:27px}.compare-row{margin:18px 0}.compare-label{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:6px;color:#63726d}.compare-label strong{font-size:18px;color:#244d49}.compare-track{height:14px;background:#eff2f0;border-radius:9px;overflow:hidden}.compare-track i{height:100%;display:block;border-radius:9px}.callout{background:#f6ebe2;border-left:3px solid #bb825f;border-radius:0 9px 9px 0;padding:12px 15px;color:#69584c;font-size:12px;line-height:1.7;margin-top:20px}
.data-card{overflow:hidden}.table-tools{display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between;padding:17px 20px;border-bottom:1px solid var(--line)}.table-actions{display:flex;gap:9px;flex-wrap:wrap;align-items:center}.table-actions select{min-width:210px}.table-tools input{width:210px}.btn{padding:9px 13px;border:1px solid #d5e2dc;border-radius:9px;background:#fff;color:#2f6560;font-weight:700;font-size:12px}.btn:hover{background:#edf6f2}.btn.primary{background:#275e57;border-color:#275e57;color:#fff}.btn.primary:hover{background:#1c4943}.table-scroll{overflow:auto;max-height:570px}table{border-collapse:collapse;min-width:100%;width:100%;font-size:12px;text-align:left}th{background:#f2f6f3;color:#65756d;text-transform:uppercase;letter-spacing:.05em;font-size:10px;position:sticky;top:0;z-index:2;white-space:nowrap}th,td{border-bottom:1px solid #e8ede8;padding:12px 13px}tr:hover td{background:#f2f8f5}td.num{font-variant-numeric:tabular-nums;text-align:right}td:first-child{font-weight:750;color:#235851;cursor:pointer}.table-status{padding:11px 20px;font-size:11px;color:#86928c;background:#fafcfb;border-top:1px solid var(--line)}
.method-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.method-card{padding:26px}.method-card h3{margin:0 0 13px;font-size:18px}.method-card p{color:#687872;margin:0 0 12px;line-height:1.7}.method-card ul{padding-left:19px;color:#64736e;margin:0}.method-card li{margin:10px 0}
.foot{border-top:1px solid #dce4de;padding:27px 0 40px;color:#7a8b84;font-size:12px}.foot-in{display:flex;justify-content:space-between;gap:12px}.live-note{margin:11px 0 0;font-size:11px;color:#81928d}.mini-dot{width:7px;height:7px;border-radius:50%;display:inline-block;background:#4e9d83;margin-right:7px}
@media(max-width:1100px){.atlas-layout{grid-template-columns:1fr}.map-side{border-left:0;border-top:1px solid var(--line);display:grid;grid-template-columns:1fr 1fr}.stat-grid{grid-template-columns:repeat(2,1fr)}.hero-in{grid-template-columns:1.5fr 1fr}.map-shell,.map-shell svg{height:480px}}
@media(max-width:760px){.max{padding:0 16px}.hero-in{padding:38px 16px;grid-template-columns:1fr;gap:19px}.hero h1{font-size:38px}.hero p{font-size:14px}.top-r .source-chip{display:none}.stat-grid,.info-grid,.two-col,.access-grid,.school-grid,.method-grid{grid-template-columns:1fr}.atlas-toolbar{padding:14px}.field,.field.small{flex-basis:100%;min-width:100%}.atlas-layout{display:block}.map-side{display:block}.map-side>div{margin-bottom:18px}.map-shell,.map-shell svg{height:375px}.map-hint{font-size:10px;bottom:8px;left:9px}.section-top{display:block}.section-top p{margin-top:8px}.bar-item{grid-template-columns:110px 1fr 30px}.toplist{grid-template-columns:1fr}.table-tools input,.table-actions select{width:100%}.table-tools,.table-actions{width:100%}.foot-in{flex-direction:column}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
.layer-toggle{display:flex;align-items:center;gap:9px;margin-top:16px;padding:11px 12px;border:1px solid var(--line);border-radius:9px;background:#fafcfb;color:var(--ink2);font-size:13px;cursor:pointer}.layer-toggle input{width:16px;height:16px;margin:0;accent-color:#47746b;cursor:pointer}.school-symbol{width:9px;height:9px;border-radius:50%;background:#e5a96b;flex:none}
</style>
</head>
<body>
<header class="top"><div class="max top-in"><div class="brand"><div class="mark">L</div><span>URBAN ATLAS<span style="color:#78958e"> / LAB</span></span></div><div class="top-r"><span class="source-chip">BlocksNet × OpenStreetMap</span><span>Учебный проект · Лодейное Поле</span></div></div></header>
<div class="hero"><div class="max hero-in"><div><div class="eyebrow">Исследование городской структуры</div><h1>Лодейное Поле.<br>Атлас кварталов</h1><p>Как устроена городская ткань: функции территории, плотность застройки, автомобильная доступность и модельная обеспеченность школами. Всё на основе сохранённых результатов BlocksNet.</p></div><div class="hero-side"><span>Доля кварталов с жилой функцией</span><strong id="hero-share">—</strong><div class="hero-meter"><i id="hero-bar"></i></div><small><span id="hero-structure-count">Распределение жилых и неклассифицированных кварталов.</span></small></div></div></div>
<nav class="nav"><div class="max nav-in"><a href="#overview">Обзор</a><a href="#atlas">Атлас</a><a href="#structure">Городская ткань</a><a href="#mobility">Доступность</a><a href="#schools">Школы</a><a href="#data">Все данные</a><a href="#details">Расчётные таблицы</a><a href="#method">Методика</a></div></nav>
<main class="max">
<section id="overview"><div class="section-top"><div><div class="section-label">01 · Портрет города</div><h2>Ключевые показатели</h2></div><p>Краткий обзор на уровне кварталов. В расчётах использованы оценки, а не официальная статистика населения и школьной вместимости.</p></div><div class="stat-grid"><div class="card stat"><span class="sub">Городские кварталы</span><strong id="s-blocks">—</strong><small>выделены на основе дорожной и водной сети</small></div><div class="card stat"><span class="sub">Площадь кварталов</span><strong id="s-area">—</strong><small>сумма геометрий кварталов</small></div><div class="card stat"><span class="sub">Модельное население</span><strong id="s-pop">—</strong><small>оценка по данным OSM о зданиях</small></div><div class="card stat"><span class="sub">Среднее время по сети</span><strong id="s-time">—</strong><small>модельная площадьно-взвешенная доступность</small></div></div><div class="info-grid"><article class="card insight"><div class="line-tag">Городская структура</div><h3>Жилая функция — основа квартальной сети</h3><p id="intro-structure"><span id="intro-structure-text">Доля жилых кварталов и пропусков классификации рассчитывается по сохранённым данным.</span></p></article><article class="card insight warning"><div class="line-tag">Ограничение данных</div><h3>Результаты — учебная модель</h3><p>Скорости автомобилей, этажность части зданий и вместимость школ оценивались. Числа подходят для сравнения кварталов внутри модели, но не заменяют полевые исследования и официальную статистику.</p></article></div></section>
<section id="atlas"><div class="section-top"><div><div class="section-label">02 · Картографический атлас</div><h2>Сравните кварталы на карте</h2></div><p>Выберите показатель и задайте фильтры. Нажмите на квартал, чтобы посмотреть подробности. Карта работает без подключения к интернету.</p></div><div class="card atlas-card"><div class="atlas-toolbar"><div class="field" style="flex:1.45"><label for="metric">Показатель на карте</label><select id="metric"></select></div><div class="field small"><label for="lu-filter">Функция</label><select id="lu-filter"></select></div><div class="field small"><label for="morph-filter">Морфотип</label><select id="morph-filter"></select></div><button class="reset" id="reset-filters">Сбросить фильтры</button></div><div class="atlas-layout"><div class="map-shell" id="map-shell"><svg id="atlas-svg" viewBox="0 0 970 590" role="img" aria-label="Интерактивная карта кварталов Лодейного Поля"><g id="map-layer"></g><g id="school-layer"></g></svg><div class="map-controls"><button id="zoom-in" class="map-btn" title="Приблизить" aria-label="Приблизить">+</button><button id="zoom-out" class="map-btn" title="Отдалить" aria-label="Отдалить">−</button><button id="zoom-reset" class="map-btn" title="Исходный вид" aria-label="Исходный вид">⌖</button></div><div class="map-tip" id="map-tip"></div><div class="map-hint">Колесо — масштаб · перетаскивание — сдвиг · нажать — детали</div></div><aside class="map-side"><div><div class="side-topline"><div class="side-head">Условные обозначения</div><span class="small-muted" id="map-count">— / —</span></div><div class="legend-list" id="legend"></div>
<label class="layer-toggle" for="show-schools"><input id="show-schools" type="checkbox" checked aria-controls="school-layer"><span class="school-symbol" aria-hidden="true"></span><span>Показывать школы</span></label>
</div><div class="divider"></div><div><div class="side-head">Выбранный квартал</div><h3 class="selected-title" id="selected-title">Выберите квартал</h3><div class="side-data" id="selected-data"><span>Нажмите на квартал на карте, чтобы увидеть его характеристики</span></div><div class="selected-note" id="selected-note" style="margin-top:17px">Числовые показатели описывают модель, а не фактическое время поездки или официальную обеспеченность населения.</div></div></aside></div></div></section>
<section id="structure"><div class="section-top"><div><div class="section-label">03 · Городская ткань</div><h2>Функции и морфология</h2></div><p>Классификации показаны по числу кварталов. Фильтры карты влияют на диаграммы; обзор города и паспорт показывают весь набор.</p></div><div class="two-col"><article class="card chart-card"><h3>Использование территории</h3><div id="land-bars"></div><p class="metric-note">Отсутствующая функция — отдельная категория.</p></article><article class="card chart-card"><h3>Морфотипы Strelka</h3><div id="morph-bars"></div><p class="metric-note">Морфотипы описывают застройку и не являются оценкой качества среды.</p></article><article class="card chart-card"><h3>Морфотипы Spacematrix</h3><div id="spacematrix-bars"></div><p class="metric-note">Группы определяются по l, FSI, MXI. Номер кластера — категория, не ранг.</p></article><article class="card chart-card"><h3>Все числовые показатели</h3><label for="distribution-metric">Выберите распределение</label><select id="distribution-metric"></select><p class="metric-note" id="distribution-note"></p><div id="metric-hist"></div></article></div><div class="two-col" style="margin-top:16px"><article class="card chart-card"><h3>Интенсивность застройки · FSI</h3><div id="fsi-hist"></div></article><article class="card chart-card"><h3>Покрытие застройкой · GSI</h3><div id="gsi-hist"></div></article></div></section>
<section id="mobility"><div class="section-top"><div><div class="section-label">04 · Модель движения</div><h2>Автомобильная доступность</h2></div><p>Показатель рассчитан по направленному автомобильному графу и площадям кварталов назначения. Его нельзя интерпретировать как реальное время поездки.</p></div><div class="access-grid"><article class="card chart-card"><h3>Распределение времени по кварталам</h3><p class="chart-caption">Площадно-взвешенное модельное время, минут</p><div id="time-hist"></div><p class="metric-note">Нулевые времена между некоторыми парами кварталов связаны с привязкой к одному узлу графа. Время от зданий до узла графа и парковки не учитывается.</p></article><article class="card chart-card"><h3>Крайние значения</h3><p class="chart-caption">Кварталы с наиболее низким и высоким расчётным временем</p><div class="toplist"><div><div class="side-head">Низкие значения</div><div id="fast-list"></div></div><div><div class="side-head">Высокие значения</div><div id="slow-list"></div></div></div><div class="chart-bottom">Сравнение показывает различия пространственного положения кварталов относительно дорожной сети.</div></article></div></section>
<section id="schools"><div class="section-top"><div><div class="section-label">05 · Образовательная инфраструктура</div><h2>Школы и расчётный спрос</h2></div><p>Обеспеченность учитывает распределение мест и конкуренцию кварталов. Нулевой спрос даёт неопределённую долю, а не 0%.</p></div><div class="school-grid"><article class="card comparison"><h3>Спрос и модельная вместимость</h3><div class="compare-row"><div class="compare-label"><span>Расчётный спрос</span><strong id="demand-value"></strong></div><div class="compare-track"><i id="demand-bar" style="background:#c68e69"></i></div></div><div class="compare-row"><div class="compare-label"><span>Модельная вместимость</span><strong id="capacity-value"></strong></div><div class="compare-track"><i id="capacity-bar" style="background:#649e94"></i></div></div><p class="metric-note" id="school-ratio"></p></article><article class="card chart-card"><h3>Доля обеспеченного спроса по городу</h3><p id="city-provision"></p><p id="school-parameters" class="metric-note"></p><p>Объектов: <strong id="school-sites">—</strong>; кварталов с определённой долей: <strong id="school-valid">—</strong>.</p><p class="metric-note">Городская доля считается через суммы спроса. Простое среднее квартальных долей — другая величина. Распределения strong и weak доступны в «Все числовые показатели».</p>__SCHOOL_DETAILS__</article></div></section>
<section id="data"><div class="section-top"><div><div class="section-label">06 · Полный набор показателей</div><h2>Исходные значения по кварталам</h2></div><p>Таблица показывает ключевые характеристики и любой дополнительный атрибут по выбору. Полный набор полей доступен в CSV.</p></div><div class="card data-card"><div class="table-tools"><div class="table-actions"><input type="search" id="table-search" placeholder="Найти квартал по ID" aria-label="Поиск квартала"><select id="extra-field" aria-label="Дополнительный показатель"></select></div><div class="table-actions"><button class="btn" id="clear-search">Сбросить поиск</button><button class="btn primary" id="export-csv">Скачать CSV · все поля</button></div></div><div class="table-scroll"><table><thead><tr><th>ID</th><th>Функция</th><th>Морфотип</th><th>Население · оценка</th><th>FSI</th><th>Время · мин</th><th id="extra-header">Доп. показатель</th></tr></thead><tbody id="data-tbody"></tbody></table></div><div class="table-status" id="table-status"></div></div></section>
<section id="details"><div class="section-top"><div><div class="section-label">07 · Воспроизводимость</div><h2>Расчётные таблицы и выводы</h2></div><p>Таблицы и CSV встроены в этот HTML. Матрица доступна целиком для скачивания без сети.</p></div>__SAVED_TABLES__</section>
<section id="method"><div class="section-top"><div><div class="section-label">08 · Методика</div><h2>Методика и качество данных</h2></div></div>__METHOD__</section>
</main>
<footer class="foot"><div class="max foot-in"><span>Лодейное Поле · Исследование кварталов на основе BlocksNet</span><span>Автономный HTML · значения из сохранённых GeoJSON и CSV, сверенные при сборке</span></div></footer>
<script id="dataset" type="application/json">__DATA__</script>
<script>
(()=>{'use strict';
const DATA=JSON.parse(document.getElementById('dataset').textContent);
const B=DATA.blocks,C=DATA.counts,L=DATA.labels,U=DATA.units;
const LU={...DATA.landNames,null:'Не определено'},MORPH={...DATA.morphNames,null:'Не определён'};
const COLORS={'residential':'#4c9b91','industrial':'#c08363','recreation':'#87af78','special':'#8980a9','null':'#b6c4c4'};
const MCP={'low-rise non-residential':'#82a9a3','low-rise model':'#d4a67a','mid-rise':'#787da9','individual residential':'#5b8270','null':'#bac4c5'};
const scaleColors=['#dfeeea','#b9d8d1','#81b9ac','#4c9385','#1c5b60'];
const el=(id)=>document.getElementById(id);
const fmt=(n,d=0)=>n==null||!Number.isFinite(Number(n))?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:d,minimumFractionDigits:d}).format(Number(n));
const label=(key)=>L[key]||key.replaceAll('_',' ');
const unit=(key)=>U[key]||'';
const cat=(x,names)=>names[String(x??null)]??String(x);
let field='land_use',filterLU='all',filterMorph='all',selected=null,extra='gsi',search='';
let view={x:0,y:0,w:970,h:590};
const svg=el('atlas-svg'),mapLayer=el('map-layer'),schoolLayer=el('school-layer');
const categories=key=>[...new Set(B.map(b=>b.p[key]??null))].sort((a,b)=>String(a).localeCompare(String(b)));
const landOrder=categories('land_use'),morphOrder=categories('strelka_morphotype'),spaceOrder=categories('spacematrix_morphotype');
for(const [i,key] of landOrder.entries())if(!(String(key) in COLORS))COLORS[String(key)]=scaleColors[i%5];
for(const [i,key] of morphOrder.entries())if(!(String(key) in MCP))MCP[String(key)]=scaleColors[i%5];
const spaceColors=Object.fromEntries(spaceOrder.map((key,i)=>[String(key),key==null?'#cbd6d3':scaleColors[i%5]]));
const allKeys=[...new Set(B.flatMap(b=>Object.keys(b.p)))];
const props=allKeys.filter(x=>x!=='block_id').sort((a,b)=>label(a).localeCompare(label(b),'ru'));
const primary=['land_use','strelka_morphotype','spacematrix_morphotype','fsi','gsi','mxi','l','osr','share_living','share_non_living','provision_strong','provision_weak','area_accessibility','population','school_count','capacity','demand'];
const groupFields=[['Основные показатели',primary.filter(k=>props.includes(k))],['Остальные атрибуты',props.filter(k=>!primary.includes(k))]];
for(const [heading,fields] of groupFields){const g=document.createElement('optgroup');g.label=heading;for(const key of fields){let o=document.createElement('option');o.value=key;o.textContent=label(key)+(unit(key)?` · ${unit(key)}`:'');g.append(o);}el('metric').append(g);}
el('metric').value=field;
for(const [v,name] of [['all','Все функции'],...landOrder.map(x=>[String(x),cat(x,LU)])]){const o=new Option(name,v);el('lu-filter').add(o);}
for(const [v,name] of [['all','Все морфотипы'],...morphOrder.map(x=>[String(x),cat(x,MORPH)])]){const o=new Option(name,v);el('morph-filter').add(o);}
for(const key of props){const o=new Option(label(key)+(unit(key)?` · ${unit(key)}`:''),key);el('extra-field').add(o);}el('extra-field').value=extra;
function shown(b){return !!b&&(filterLU==='all'||String(b.p.land_use??null)===filterLU)&&(filterMorph==='all'||String(b.p.strelka_morphotype??null)===filterMorph);}
function visible(){return B.filter(shown);}
function isNumeric(key){return key!=='spacematrix_cluster'&&B.some(b=>typeof b.p[key]==='number'&&Number.isFinite(b.p[key]));}
function valueString(x,k){if(x==null)return 'Нет данных';if(k==='land_use')return cat(x,LU);if(k==='strelka_morphotype'||k==='spacematrix_morphotype')return cat(x,MORPH);if(typeof x==='boolean')return x?'Да':'Нет';if(typeof x==='number')return fmt(x,['area_accessibility','fsi','gsi','provision_strong','provision_weak','mxi','osr','reachable_area_share','share','l','share_living','share_non_living','residential','business','recreation','industrial','transport','special','agriculture','snap_distance_m'].includes(k)?3:0)+(unit(k)?' '+unit(k):'');return String(x);}
function domain(k){const vals=B.map(x=>x.p[k]).filter(v=>typeof v==='number'&&Number.isFinite(v));return vals.length?[Math.min(...vals),Math.max(...vals)]:[0,1];}
function palette(v,k){if(v==null)return '#cbd6d3';if(k==='land_use')return COLORS[String(v)]||COLORS.null;if(k==='strelka_morphotype')return MCP[String(v)]||MCP.null;if(!isNumeric(k)){let values=[...new Set(B.map(b=>b.p[k]).filter(v=>v!=null))].sort();return scaleColors[Math.max(0,values.indexOf(v))%5];}if(typeof v!=='number')return '#cbd6d3';const [min,max]=domain(k);const t=max===min?0.5:(v-min)/(max-min);return scaleColors[Math.min(4,Math.max(0,Math.floor(t*5)))];}
let shapes=new Map();
for(const b of B){const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',b.d);path.setAttribute('data-id',String(b.id));path.setAttribute('class','geo');path.setAttribute('tabindex','0');path.setAttribute('aria-label','Квартал '+b.id);path.addEventListener('mouseenter',e=>{tooltip(e,b);});path.addEventListener('mousemove',e=>tooltip(e,b));path.addEventListener('mouseleave',()=>{el('map-tip').style.display='none';});path.addEventListener('click',()=>{selected=b.id;updateSelect();});path.addEventListener('keydown',e=>{if(e.key==='Enter'){selected=b.id;updateSelect();}});mapLayer.append(path);shapes.set(b.id,path);}
function tooltip(evt,b){const t=el('map-tip'),r=el('map-shell').getBoundingClientRect();t.textContent=`Квартал №${b.id} · ${valueString(b.p[field],field)}`;t.style.display='block';t.style.left=(Math.min(evt.clientX-r.left+13,r.width-220))+'px';t.style.top=(Math.max(10,evt.clientY-r.top-50))+'px';}
function schoolDots(){schoolLayer.replaceChildren();if(!el('show-schools').checked)return;for(const school of DATA.schools){
 const b=B.find(x=>x.id===school.block_id);if(!shown(b))continue;
 const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('cx',school.cx);dot.setAttribute('cy',school.cy);dot.setAttribute('r',4);dot.setAttribute('fill','#e5a96b');dot.setAttribute('stroke','#fff');dot.setAttribute('stroke-width','1.5');
 dot.setAttribute('data-school-id',school.id);dot.setAttribute('data-block-id',school.block_id);dot.style.cursor='pointer';
 const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=school.name+' · квартал №'+school.block_id;dot.append(title);
 dot.addEventListener('click',()=>{selected=school.block_id;updateSelect();});schoolLayer.append(dot);
}}
function drawMap(){for(const b of B){const p=shapes.get(b.id);p.setAttribute('fill',palette(b.p[field],field));p.classList.toggle('dim',!shown(b));p.classList.toggle('focused',b.id===selected);}schoolDots();el('map-count').textContent=visible().length+' / '+B.length;drawLegend();}
function drawLegend(){const box=el('legend');box.replaceChildren();let items=[];
 if(field==='land_use')items=landOrder.map(k=>[cat(k,LU),COLORS[String(k)],visible().filter(b=>b.p.land_use===k).length]);
 else if(field==='strelka_morphotype')items=morphOrder.map(k=>[cat(k,MORPH),MCP[String(k)],visible().filter(b=>b.p.strelka_morphotype===k).length]);
 else if(field==='school_count'){
  const counts=categories(field).sort((a,b)=>a==null?1:b==null?-1:a-b);
  const schoolNames={one:'школа',few:'школы',many:'школ',other:'школы'},plural=new Intl.PluralRules('ru-RU');
  items=counts.map(k=>[k==null?'Нет данных':k===0?'Нет школ':`${fmt(k)} ${schoolNames[plural.select(k)]}`,palette(k,field),visible().filter(b=>(b.p[field]??null)===k).length]);
 }
 else if(isNumeric(field)){const [mi,ma]=domain(field);for(let i=0;i<5;i++){const a=mi+(ma-mi)*i/5,z=mi+(ma-mi)*(i+1)/5;items.push([`${fmt(a,2)} – ${fmt(z,2)}`,scaleColors[i],null]);}const missing=visible().filter(b=>b.p[field]==null).length;if(missing)items.push(['Нет данных','#cbd6d3',missing]);}
 else {const keys=[...new Set(visible().map(b=>b.p[field]??null))];items=keys.map(k=>[valueString(k,field),palette(k,field),visible().filter(b=>(b.p[field]??null)===k).length]);}
 for(const [name,c,count] of items){const row=document.createElement('div');row.className='legend-item';const a=document.createElement('span');a.className='legend-text';const sw=document.createElement('i');sw.className='swatch';sw.style.background=c;const labelEl=document.createElement('span');labelEl.textContent=name;a.append(sw,labelEl);row.append(a);if(count!==null){const right=document.createElement('span');right.className='legend-count';right.textContent=fmt(count);row.append(right);}box.append(row);}
}
function updateSelect(){drawMap();const b=B.find(x=>x.id===selected);if(!b){el('selected-title').textContent='Выберите квартал';el('selected-data').replaceChildren();const span=document.createElement('span');span.textContent='Нажмите на квартал на карте, чтобы увидеть его характеристики';el('selected-data').append(span);return;}el('selected-title').textContent='Квартал №'+b.id;const vals=[['Функция',valueString(b.p.land_use,'land_use')],['Морфотип',valueString(b.p.strelka_morphotype,'strelka_morphotype')],['FSI',valueString(b.p.fsi,'fsi')],['GSI',valueString(b.p.gsi,'gsi')],['Доступность',valueString(b.p.area_accessibility,'area_accessibility')],['Население',valueString(b.p.population,'population')],['Школьных объектов',valueString(b.p.school_count,'school_count')],['Текущий показатель',valueString(b.p[field],field)]];let panel=el('selected-data');panel.replaceChildren();for(let [key,value] of vals){let a=document.createElement('span'),c=document.createElement('strong');a.textContent=key;c.textContent=value;panel.append(a,c);}}
function drawBars(target,category,order,nameMap,colorMap){const dest=el(target);dest.replaceChildren();const vis=visible(),maximum=vis.length||1;for(const key of order){const count=vis.filter(b=>(b.p[category]??null)===key).length;const row=document.createElement('div');row.className='bar-item';const text=document.createElement('label');text.textContent=cat(key,nameMap);const track=document.createElement('div');track.className='bar-track';const bar=document.createElement('div');bar.className='bar-fill';bar.style.width=(count/maximum*100)+'%';bar.style.background=colorMap[String(key)];track.append(bar);const value=document.createElement('span');value.className='bar-number';value.textContent=fmt(count);row.append(text,track,value);dest.append(row);}}
function hist(id,key){const root=el(id);root.replaceChildren();const vv=visible().map(b=>b.p[key]).filter(v=>typeof v==='number'&&Number.isFinite(v));if(!vv.length){root.textContent='Нет значений для выбранного фильтра';return;}
 const mi=Math.min(...vv),ma=Math.max(...vv),bins=Math.min(20,Math.max(1,vv.length)),counts=new Array(bins).fill(0);const lo=ma===mi?mi-.5:mi,hi=ma===mi?ma+.5:ma;for(const v of vv){const ix=Math.min(bins-1,Math.floor((v-lo)/(hi-lo)*bins));counts[ix]++;}const peak=Math.max(1,...counts);const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 540 195');svg.setAttribute('class','hist-svg');svg.setAttribute('role','img');svg.setAttribute('aria-label',label(key)+' — распределение значений');let bars='';counts.forEach((c,i)=>{const step=486/bins,bw=Math.max(1,step-3),x=40+i*step,hei=c/peak*139,y=158-hei;bars+=`<rect x="${x}" y="${y}" width="${bw}" height="${hei}" rx="3" fill="${i%2?'#6aa397':'#3a817b'}"/><text x="${x+bw/2}" y="${y-6}" text-anchor="middle" font-size="11" fill="#71847d">${c}</text>`;});svg.innerHTML='<line x1="30" y1="158" x2="526" y2="158" stroke="#dbe5e0"/>'+bars;root.append(svg);const foot=document.createElement('div');foot.className='hist-range';foot.innerHTML=`<span>${fmt(lo,2)} ${unit(key)}</span><span>Кварталов: ${vv.length} · интервалов: ${bins}</span><span>${fmt(hi,2)} ${unit(key)}</span>`;root.append(foot);}
function outliers(){const vis=visible().filter(b=>Number.isFinite(b.p.area_accessibility)).slice().sort((a,b)=>a.p.area_accessibility-b.p.area_accessibility);const fill=(id,arr)=>{const root=el(id);root.replaceChildren();for(const b of arr){let row=document.createElement('div');row.className='topline';row.innerHTML=`<span>№ ${b.id}</span><strong>${fmt(b.p.area_accessibility,2)} мин</strong>`;row.addEventListener('click',()=>{selected=b.id;updateSelect();document.getElementById('atlas').scrollIntoView({behavior:'smooth'});});row.style.cursor='pointer';root.append(row);}};fill('fast-list',vis.slice(0,5));fill('slow-list',vis.slice(-5).reverse());}
function drawTable(){const tb=el('data-tbody');tb.replaceChildren();const ids=visible().filter(b=>!search||String(b.id).includes(search));for(const b of ids){let tr=document.createElement('tr');const p=b.p;let values=[b.id,valueString(p.land_use,'land_use'),valueString(p.strelka_morphotype,'strelka_morphotype'),fmt(p.population),fmt(p.fsi,3),fmt(p.area_accessibility,2),valueString(p[extra],extra)];for(let i=0;i<values.length;i++){let td=document.createElement('td');td.textContent=values[i];if(i===3||i===4||i===5)td.className='num';tr.append(td);}tr.addEventListener('click',()=>{selected=b.id;updateSelect();document.getElementById('atlas').scrollIntoView({behavior:'smooth'});});tb.append(tr);}el('extra-header').textContent=label(extra);el('table-status').textContent=`Показано ${ids.length} из ${B.length} кварталов · ${Object.keys(B[0].p).length} атрибутов, все доступны в CSV`;
}
const mainNumeric=['fsi','gsi','mxi','l','osr','share_living','share_non_living','provision_strong','provision_weak','area_accessibility'];
const numericMetrics=[...mainNumeric,...props.filter(k=>isNumeric(k)&&!mainNumeric.includes(k))];
const notes={fsi:'Поэтажная площадь / площадь квартала.',gsi:'Пятно зданий / площадь квартала.',mxi:'Жилая площадь / поэтажная площадь; не универсальная оценка разнообразия функций.',l:'Поэтажная площадь / пятно зданий; среднее, взвешенное площадями.',osr:'(Площадь квартала − пятно зданий) / поэтажная площадь. Это не доля зелени.',share_living:'Жилая площадь / пятно зданий. Может быть больше 1.',share_non_living:'Нежилая площадь / пятно зданий. Может быть больше 1.',provision_strong:'Доля удовлетворённого спроса в пороге автомобильного времени.',provision_weak:'Доля удовлетворённого спроса с расширением поиска; при max_depth=1 совпадает со strong.',area_accessibility:'Среднее время из квартала, взвешенное площадями назначений; меньше — быстрее.'};
for(const key of numericMetrics)el('distribution-metric').add(new Option(label(key)+' · '+unit(key),key));
function drawDistribution(){const key=el('distribution-metric').value;hist('metric-hist',key);const missing=visible().filter(b=>b.p[key]==null).length;el('distribution-note').textContent=(notes[key]||label(key)+'.')+' Нет определённых значений: '+missing+' из '+visible().length+'.';}
el('distribution-metric').addEventListener('change',drawDistribution);
function update(){selected=selected!=null&&shown(B.find(b=>b.id===selected))?selected:null;drawMap();updateSelect();drawBars('land-bars','land_use',landOrder,LU,COLORS);drawBars('morph-bars','strelka_morphotype',morphOrder,MORPH,MCP);drawBars('spacematrix-bars','spacematrix_morphotype',spaceOrder,MORPH,spaceColors);hist('fsi-hist','fsi');hist('gsi-hist','gsi');hist('time-hist','area_accessibility');drawDistribution();outliers();drawTable();}
function setView(){svg.setAttribute('viewBox',`${view.x} ${view.y} ${view.w} ${view.h}`);}
function zoom(factor){const cx=view.x+view.w/2,cy=view.y+view.h/2;const w=Math.min(1300,Math.max(90,view.w*factor)),h=w*590/970;view={x:cx-w/2,y:cy-h/2,w,h};setView();}
el('show-schools').addEventListener('change',schoolDots);
el('zoom-in').addEventListener('click',()=>zoom(.77));el('zoom-out').addEventListener('click',()=>zoom(1.3));el('zoom-reset').addEventListener('click',()=>{view={x:0,y:0,w:970,h:590};setView();});
svg.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.13:.88);},{passive:false});let drag=null;svg.addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY,ox:view.x,oy:view.y,move:false};});svg.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)<=3&&!drag.move)return;if(!drag.move){drag.move=true;svg.setPointerCapture(e.pointerId);}const rect=svg.getBoundingClientRect();view.x=drag.ox-dx/rect.width*view.w;view.y=drag.oy-dy/rect.height*view.h;setView();});svg.addEventListener('pointerup',()=>{drag=null;});svg.addEventListener('pointercancel',()=>{drag=null;});
el('metric').addEventListener('change',e=>{field=e.target.value;updateSelect();});el('lu-filter').addEventListener('change',e=>{filterLU=e.target.value;update();});el('morph-filter').addEventListener('change',e=>{filterMorph=e.target.value;update();});el('reset-filters').addEventListener('click',()=>{filterLU='all';filterMorph='all';selected=null;el('lu-filter').value='all';el('morph-filter').value='all';update();});el('extra-field').addEventListener('change',e=>{extra=e.target.value;drawTable();});el('table-search').addEventListener('input',e=>{search=e.target.value.trim();drawTable();});el('clear-search').addEventListener('click',()=>{search='';el('table-search').value='';drawTable();});
el('export-csv').addEventListener('click',()=>{const keys=allKeys;const quote=v=>'"'+String(v==null?'':v).replaceAll('"','""')+'"';const text='\ufeff'+[keys.join(';'),...visible().filter(b=>!search||String(b.id).includes(search)).map(b=>keys.map(k=>quote(b.p[k])).join(';'))].join('\r\n');const blob=new Blob([text],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='lodeynoye_pole_blocks_filtered.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1500);});
const N=Intl.NumberFormat('ru-RU');el('s-blocks').textContent=fmt(C.total);el('s-area').textContent=fmt(C.totalArea/1e6,2)+' км²';el('s-pop').textContent=fmt(C.population);el('s-time').textContent=fmt(C.avgTime,2)+' мин';el('hero-structure-count').textContent=fmt(C.residential)+' из '+fmt(C.total)+' кварталов классифицированы как жилые; '+fmt(C.missing)+' кварталов без определённой функции.';el('intro-structure-text').textContent=fmt(C.residential)+' кварталов отмечены как жилые, а '+fmt(C.missing)+' не получили классификацию по OSM. Их следует учитывать отдельно при сравнении территорий.';el('hero-share').textContent=fmt(100*C.residential/C.total,1)+'%';el('hero-bar').style.width=100*C.residential/C.total+'%';el('demand-value').textContent=fmt(C.demand)+' мест';el('capacity-value').textContent=fmt(C.capacity)+' мест';el('demand-bar').style.width='100%';el('capacity-bar').style.width=100*C.capacity/C.demand+'%';el('school-ratio').textContent='Модельная вместимость / модельный спрос = '+fmt(100*C.capacity/C.demand,1)+'%. Это сравнение сумм, не подтверждённая доля обеспеченных детей.';el('school-sites').textContent=fmt(C.schools);el('school-valid').textContent=fmt(C.provisionCount);
update();
const S=DATA.summary,A=S.assumptions;
el('city-provision').textContent='Strong: '+(S.city_provision_strong==null?'—':fmt(100*S.city_provision_strong,2)+'%')+' · Weak: '+(S.city_provision_weak==null?'—':fmt(100*S.city_provision_weak,2)+'%');
el('school-parameters').textContent=A.school_demand_per_1000+' мест на 1000 жителей; '+A.school_accessibility_min+' автомобильных минут; глубина поиска '+A.provision_max_depth+'.';
const comparisonMax=Math.max(C.capacity,C.demand,1);
el('demand-bar').style.width=100*C.demand/comparisonMax+'%';
el('capacity-bar').style.width=100*C.capacity/comparisonMax+'%';
el('school-ratio').textContent=C.demand>0?'Вместимость / спрос = '+fmt(100*C.capacity/C.demand,2)+'%. Это отношение сумм; обеспеченность показана отдельно.':'При нулевом спросе отношение и доли обеспеченности не определены.';
})();
</script>
</body>
</html>'''


def build_dashboard() -> Path:
    features = load_results()
    summary = read_json(RESULTS_DIR / 'summary.json')
    audit_results(features, summary)
    data = make_dataset(features, summary)
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data_json = data_json.replace("</", "<\\/")
    page = TEMPLATE.replace("__SAVED_TABLES__", saved_tables_html(summary, features))
    page = page.replace("__SCHOOL_DETAILS__", school_details_html()).replace("__METHOD__", method_html(summary))
    page = page.replace("__DATA__", data_json)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Пересоздаём тот же dashboard.html, что использовался раньше.
    OUTPUT_FILE.write_text(page, encoding="utf-8")
    print(f"Дашборд создан: {OUTPUT_FILE}")
    print(f"Кварталов: {data['counts']['total']}; размер HTML: {OUTPUT_FILE.stat().st_size / 1024:.0f} КБ")
    print("Сверка GeoJSON/CSV, плотности, школьных балансов, матрицы, сводных таблиц и паспорта пройдена.")
    return OUTPUT_FILE


if __name__ == "__main__":
    build_dashboard()
