
from pathlib import Path
from datetime import datetime, timezone

import geopandas as gpd
import osmnx as ox

# Папка исследования
DATA = Path(__file__).resolve().parent / "data" / "lodeynoye_pole"

# Исходная граница города
boundary_file = DATA / "raw" / "boundary.geojson"

# Итоговый граф
graph_file = DATA / "graph" / "drive.graphml"
graph_file.parent.mkdir(parents=True, exist_ok=True)

if graph_file.exists():
    raise SystemExit(
        f"Граф уже существует: {graph_file}. "
        "Существующий файл не перезаписываем."
    )

# Читаем сохранённую границу
boundary = gpd.read_file(boundary_file)

if boundary.crs is None:
    raise ValueError("У границы не указана система координат")

# Добавляем окрестности города — 3 км
boundary_local = boundary.to_crs("EPSG:32636")
polygon_local = boundary_local.geometry.union_all().buffer(3000)

polygon_wgs84 = gpd.GeoSeries(
    [polygon_local], crs="EPSG:32636"
).to_crs("EPSG:4326").iloc[0]

# Настройки загрузки OpenStreetMap
ox.settings.use_cache = True
ox.settings.requests_timeout = 240

print("1. Загружаю автомобильную сеть Лодейного Поля...")

G = ox.graph_from_polygon(
    polygon_wgs84,
    network_type="drive",
    simplify=True,
    retain_all=False
)

# Подсчёт участков с указанной скоростью в OSM
known_speeds = sum(
    bool(data.get("maxspeed"))
    for _, _, _, data in G.edges(keys=True, data=True)
)

print("Узлов:", G.number_of_nodes())
print("Участков дорог:", G.number_of_edges())
print("Участков с maxspeed:", known_speeds)

# Допущения для участков без известных скоростей, км/ч
assumed_speeds = {
    "living_street": 10,
    "service": 20,
    "residential": 30,
    "unclassified": 30,
    "tertiary": 40,
    "secondary": 50,
    "primary": 60,
    "trunk": 90,
}

# Устанавливаем скорости и рассчитываем время
G = ox.add_edge_speeds(
    G,
    hwy_speeds=assumed_speeds,
    fallback=30
)
G = ox.add_edge_travel_times(G)

# Переводим координаты в метры
G = ox.project_graph(G, to_crs="EPSG:32636")

# Сведения о происхождении графа
G.graph["mode"] = "drive"
G.graph["source"] = "OpenStreetMap via OSMnx"
G.graph["source_date"] = datetime.now(
    timezone.utc
).date().isoformat()
G.graph["time_method"] = "modelled_free_flow"

# Проверяем время на всех участках
for _, _, _, data in G.edges(keys=True, data=True):
    if float(data["travel_time"]) < 0:
        raise ValueError("Обнаружено отрицательное время")

# Сохраняем GraphML
ox.save_graphml(G, filepath=graph_file)

print("2. ГРАФ УСПЕШНО СОХРАНЁН!")
print("Файл:", graph_file)
print("CRS: EPSG:32636")
print("Поле времени: travel_time")
print("Единица времени: seconds")
print("Дата получения:", G.graph["source_date"])
