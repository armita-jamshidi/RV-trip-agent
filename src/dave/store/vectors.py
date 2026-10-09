"""Search campgrounds by meaning ("quiet lakeside with mountain views") plus hard filters.

Callers use `CampgroundIndex`; LanceDB is an implementation detail, so pgvector could replace
it behind the same two methods. Filters keep only campgrounds *known* to match (hookups,
RV length, distance). Unknown values are T14's job, which flags them as "call to confirm".
"""

import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

import lancedb

from dave.geo import Point, haversine_miles
from dave.models import Campground, Hookup

INDEX_PATH = Path("data/campgrounds.lance")
TABLE = "campgrounds"
MILES_PER_DEG_LAT = 69.0


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """Open bge-small model run locally on CPU (ONNX via fastembed). Downloads once, then cached.

    `model_path` loads a fine-tuned copy instead (an ONNX export of bge-small, see T30). Build and
    search the index with the same model: their vectors aren't comparable.
    """

    MODEL = "BAAI/bge-small-en-v1.5"
    TUNED = "dave/campgrounds-bge-small"

    def __init__(self, cache_dir: Path | str, model_path: Path | None = None) -> None:
        from fastembed import TextEmbedding  # slow import; only when actually embedding

        if model_path is None:
            self._model = TextEmbedding(self.MODEL, cache_dir=str(cache_dir))
            return
        from fastembed.common.model_description import ModelSource, PoolingType

        if self.TUNED not in {m["model"] for m in TextEmbedding.list_supported_models()}:
            TextEmbedding.add_custom_model(
                model=self.TUNED,
                pooling=PoolingType.CLS,  # as bge-small
                normalization=True,
                sources=ModelSource(hf=self.MODEL),  # never fetched: the files are local
                dim=384,
            )
        self._model = TextEmbedding(
            self.TUNED, cache_dir=str(cache_dir), specific_model_path=str(model_path)
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


def campground_text(c: Campground) -> str:
    """What gets embedded: the name, the description and the facts a traveler would ask about."""
    facts = []
    if c.hookups:
        facts.append(" and ".join(sorted(h.value for h in c.hookups)) + " hookups")
    if c.electrical_amps:
        facts.append("/".join(map(str, sorted(c.electrical_amps))) + " amp")
    if c.max_rv_length_ft:
        facts.append(f"sites up to {c.max_rv_length_ft:.0f} ft")
    return ". ".join(filter(None, [c.name, c.description, ", ".join(facts)]))


class CampgroundIndex:
    def __init__(self, path: Path | str, embedder: Embedder) -> None:
        self._db = lancedb.connect(str(path))
        self._embedder = embedder

    def build(self, campgrounds: Iterable[Campground]) -> int:
        """Replace the index with these campgrounds. Returns how many were indexed."""
        campgrounds = list(campgrounds)
        if not campgrounds:
            raise ValueError("No campgrounds to index; run `dave campgrounds` first.")
        vectors = self._embedder.embed([campground_text(c) for c in campgrounds])
        rows = [_row(c, v) for c, v in zip(campgrounds, vectors, strict=True)]
        self._db.create_table(TABLE, data=rows, mode="overwrite")
        return len(rows)

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        hookups: Iterable[Hookup] = (),
        min_length_ft: float | None = None,
        near: Point | None = None,
        radius_miles: float | None = None,
    ) -> list[tuple[Campground, float]]:
        """Top `k` matches as (campground, similarity from -1 to 1), best first."""
        where = [f"has_{h.value}" for h in sorted(set(hookups))]
        if min_length_ft:
            where.append(f"max_rv_length_ft >= {float(min_length_ft)}")
        if near and radius_miles:
            where.append(_bounding_box(near, radius_miles))

        search = self._db.open_table(TABLE).search(self._embedder.embed_query(query))
        search = search.distance_type("cosine")
        if where:
            search = search.where(" AND ".join(where), prefilter=True)
        # Fetch extra so the exact distance check below can still fill `k`.
        rows = search.limit(k * 4 if near else k).to_list()

        results = []
        for row in rows:
            camp = Campground.model_validate_json(row["data"])
            if near and radius_miles:
                if haversine_miles(near, (camp.location.lat, camp.location.lon)) > radius_miles:
                    continue
            results.append((camp, 1 - row["_distance"]))
        return results[:k]


def _row(c: Campground, vector: list[float]) -> dict:
    return {
        "vector": vector,
        "name": c.name,
        "lat": c.location.lat,
        "lon": c.location.lon,
        **{f"has_{h.value}": h in c.hookups for h in Hookup},
        "max_rv_length_ft": float(c.max_rv_length_ft or 0),
        "data": json.dumps(c.model_dump(mode="json")),
    }


def _bounding_box(center: Point, radius_miles: float) -> str:
    lat, lon = center
    dlat = radius_miles / MILES_PER_DEG_LAT
    dlon = radius_miles / (MILES_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01))
    return (
        f"lat BETWEEN {lat - dlat} AND {lat + dlat} AND lon BETWEEN {lon - dlon} AND {lon + dlon}"
    )
