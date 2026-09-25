"""Génère src/geo_outlines.py : contours simplifiés (chemins SVG) des zones et pays.

OUTIL DE DÉVELOPPEMENT : à lancer à la main une fois. L'app en production n'en dépend pas
(elle ne lit que le fichier généré, sans réseau ni dépendance géographique).

Dépendances (à installer localement, PAS dans requirements.txt) : pip install shapely pyproj
Données : Natural Earth 50m admin-0 countries (domaine public).
"""
import json
import urllib.request
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import MultiPolygon, box, shape
from shapely.ops import transform, unary_union

URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
       "geojson/ne_50m_admin_0_countries.geojson")
SRC = Path("tools/ne_50m_admin_0_countries.geojson")   # ~3 Mo : ne pas committer
OUT = Path("src/geo_outlines.py")
LARGEUR = 400  # taille du plus grand côté dans le viewBox

ZONE_EURO = {
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Estonia", "Finland", "France", "Germany",
    "Greece", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands",
    "Portugal", "Slovakia", "Slovenia", "Spain",
}

# clé : (filtre sur les propriétés, cadre (ouest, sud, est, nord) ou None, finesse)
# finesse : plus le nombre est grand, plus le tracé est détaillé (donc lourd)
FORMES = {
    "europe":      (lambda p: p["CONTINENT"] == "Europe" and p["ADMIN"] != "Russia", (-25, 34, 45, 72), 150),
    "amerique":    (lambda p: p["CONTINENT"] in ("North America", "South America") and p["ADMIN"] != "Greenland", (-170, -56, -30, 72), 130),
    "asie":        (lambda p: p["CONTINENT"] == "Asia" and p["ADMIN"] != "Russia", (25, -11, 150, 56), 130),
    "france":      (lambda p: p["ADMIN"] == "France", (-6, 41, 10, 52), 200),
    "allemagne":   (lambda p: p["ADMIN"] == "Germany", None, 200),
    "royaume-uni": (lambda p: p["ADMIN"] == "United Kingdom", (-11, 49, 2, 61), 170),
    "suisse":      (lambda p: p["ADMIN"] == "Switzerland", None, 170),
    "pays-bas":    (lambda p: p["ADMIN"] == "Netherlands", (3, 50.5, 8, 54), 170),
    "etats-unis":  (lambda p: p["ADMIN"] == "United States of America", (-125, 24, -66, 50), 170),
    "canada":      (lambda p: p["ADMIN"] == "Canada", (-141, 41, -52, 75), 150),
    "japon":       (lambda p: p["ADMIN"] == "Japan", (128, 30, 146, 46), 170),
    "chine":       (lambda p: p["ADMIN"] == "China", None, 150),
    # Hong Kong volontairement absent : à la résolution 50m, sa forme est trop
    # grossière pour être reconnaissable (vérifié visuellement le 25/09/2026) ;
    # la carte Hong Kong s'affiche donc sans contour.
    "australie":   (lambda p: p["ADMIN"] == "Australia", (112, -44, 154, -10), 150),
    "nouvelle-zelande": (lambda p: p["ADMIN"] == "New Zealand", (165, -48, 179, -34), 170),  # carte NZD (Forex)
    # Zone euro : liste à VÉRIFIER auprès de la BCE avant mise en production (elle évolue)
    "zone-euro":   (lambda p: p["ADMIN"] in ZONE_EURO, (-12, 34, 35, 61), 150),
}


def charger():
    if not SRC.exists():
        SRC.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(URL, SRC)
    return json.loads(SRC.read_text(encoding="utf-8"))["features"]


def chemin(geom, finesse):
    """Projette (LAEA centrée sur la forme), simplifie et renvoie (d, largeur, hauteur)."""
    c = geom.centroid
    proj = f"+proj=laea +lat_0={c.y:.3f} +lon_0={c.x:.3f} +datum=WGS84 +units=m"
    t = Transformer.from_crs("EPSG:4326", proj, always_xy=True)
    g = transform(lambda x, y, z=None: t.transform(x, y), geom)
    minx, miny, maxx, maxy = g.bounds
    g = g.simplify(max(maxx - minx, maxy - miny) / finesse, preserve_topology=True)
    polys = list(g.geoms) if isinstance(g, MultiPolygon) else [g]
    total = sum(p.area for p in polys)
    polys = [p for p in polys if p.area > total * 0.0015]  # écarte les îlots minuscules
    minx, miny, maxx, maxy = unary_union(polys).bounds
    s = LARGEUR / max(maxx - minx, maxy - miny)
    d = "".join(
        "M" + " L".join(f"{(x - minx) * s:.0f} {(maxy - y) * s:.0f}" for x, y in p.exterior.coords) + "Z"
        for p in polys
    )
    return d, round((maxx - minx) * s), round((maxy - miny) * s)


def main():
    feats = charger()
    sortie = {}
    for cle, (filtre, cadre, finesse) in FORMES.items():
        geoms = [shape(f["geometry"]) for f in feats if filtre(f["properties"])]
        if not geoms:
            raise SystemExit(f"Aucune géométrie pour {cle} : vérifier le filtre")
        g = unary_union(geoms)
        if cadre:
            g = g.intersection(box(*cadre))
        d, w, h = chemin(g, finesse)
        sortie[cle] = {"w": w, "h": h, "d": d}
        print(f"{cle:12s} {w}x{h}  {len(d)/1024:.1f} Ko")
    lignes = ['"""Contours géographiques générés par tools/generer_contours.py. NE PAS ÉDITER À LA MAIN."""', "", "GEO_OUTLINES = {"]
    for cle, v in sortie.items():
        lignes.append(f'    "{cle}": {{"w": {v["w"]}, "h": {v["h"]}, "d": "{v["d"]}"}},')
    lignes.append("}")
    OUT.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print("Écrit :", OUT)


if __name__ == "__main__":
    main()
