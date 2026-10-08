"""Road routes from OSRM (OpenStreetMap), with RV drive times."""

from dave.http import CachedClient
from dave.models import Place, Route, RouteLeg

OSRM_URL = "https://router.project-osrm.org"
RV_SPEED_FACTOR = 1.10  # RVs take about 10% longer than OSRM's car times
METERS_PER_MILE = 1609.344


class RoutingError(RuntimeError):
    pass


def route(
    points: list[Place],
    http: CachedClient,
    *,
    base_url: str = OSRM_URL,
    speed_factor: float = RV_SPEED_FACTOR,
) -> Route:
    """Driving route through `points` in order (origin, waypoints..., destination)."""
    if len(points) < 2:
        raise ValueError("A route needs at least an origin and a destination.")
    coords = ";".join(f"{p.lon},{p.lat}" for p in points)
    response = http.get(
        f"{base_url}/route/v1/driving/{coords}",
        params={"overview": "full", "geometries": "geojson", "steps": "false"},
    )
    data = response.json()
    if not response.is_success or data.get("code") != "Ok" or not data.get("routes"):
        names = " → ".join(p.name for p in points)
        raise RoutingError(f"No route for {names}: {data.get('message') or data.get('code')}")

    best = data["routes"][0]
    return Route(
        miles=best["distance"] / METERS_PER_MILE,
        car_hours=best["duration"] / 3600,
        drive_hours=best["duration"] / 3600 * speed_factor,
        legs=[
            RouteLeg(
                miles=leg["distance"] / METERS_PER_MILE,
                drive_hours=leg["duration"] / 3600 * speed_factor,
            )
            for leg in best["legs"]
        ],
        geometry=[(lat, lon) for lon, lat in best["geometry"]["coordinates"]],
    )
